"""Corrective retrieval loop: retrieve → grade → re-query (ADR-029).

A single-shot retrieval pass is brittle: weak evidence flows straight into
generation and surfaces as a confident wrong answer. :class:`CorrectiveRetriever`
wraps the ADR-028 hybrid retriever in a Corrective-RAG style loop — grade the
evidence, and on a failed grade rewrite the query and retrieve again — mirroring
the budget discipline of the ADR-013 reasoning loop as a plain class: the loop is
bounded both by ``max_attempts`` and by an optional duck-typed budget object
(``check_before_step()`` / ``record_step()``, the
:class:`~mira.orchestration.reasoning.ReasoningBudget` surface) without importing
orchestration, so retrieval stays framework-free (ADR-001/ADR-007 containment).

The grader and rewriter are plain callables. The deterministic defaults —
top-score threshold grading; query relaxation that drops out-of-vocabulary tokens,
then the most common (lowest-idf) token — are offline reference implementations;
live-model grading (an LLM relevance critic) and live-model query rewriting plug
into the same hooks later (ADR-029 deferred item).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from mira.retrieval.hybrid import HybridRetriever
from mira.retrieval.inmemory import tokenize
from mira.retrieval.protocols import SearchHit

Grader = Callable[[str, list[SearchHit]], bool]
Rewriter = Callable[[str, int], str]


@runtime_checkable
class StepBudget(Protocol):
    """Duck-typed step budget (the ADR-013 ``ReasoningBudget`` surface, no import)."""

    def check_before_step(self) -> Any:
        """Return a truthy bound-exceeded marker when the budget is spent, else None."""
        ...

    def record_step(self) -> None:
        """Consume one step."""
        ...


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    """Result of a corrective retrieval run: final hits plus loop telemetry."""

    hits: tuple[SearchHit, ...]
    attempts: int
    corrected: bool
    budget_exhausted: bool
    queries: tuple[str, ...] = field(default=())


class CorrectiveRetriever:
    """Bounded retrieve → grade → re-query loop over a hybrid retriever (ADR-029)."""

    def __init__(
        self,
        retriever: HybridRetriever,
        *,
        grader: Grader | None = None,
        rewriter: Rewriter | None = None,
        max_attempts: int = 3,
        k: int = 3,
        min_top_score: float = 0.0,
        budget: StepBudget | None = None,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError(f"max_attempts must be positive, got {max_attempts}")
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")
        self._retriever = retriever
        self._grader = grader if grader is not None else self._default_grader
        self._rewriter = rewriter if rewriter is not None else self._default_rewriter
        self._max_attempts = max_attempts
        self._k = k
        self._min_top_score = min_top_score
        self._budget = budget

    def _default_grader(self, query: str, hits: list[SearchHit]) -> bool:
        """Accept when hits are non-empty and the top score clears the threshold."""
        return bool(hits) and hits[0].score >= self._min_top_score

    def _default_rewriter(self, query: str, attempt: int) -> str:
        """Deterministic query relaxation against the sparse index's vocabulary.

        First drop tokens with zero document frequency (out-of-vocabulary terms are
        what make a query over-specific); if every token is known, drop the single
        lowest-idf (most common, least discriminating) token. If nothing can be
        dropped, append an attempt marker so the loop never re-runs an identical query.
        """
        sparse = self._retriever.sparse
        tokens = tokenize(query)
        known = [t for t in tokens if sparse.document_frequency(t) > 0]
        if known and len(known) < len(tokens):
            return " ".join(known)
        if len(known) > 1:
            most_common = min(known, key=lambda t: (sparse.idf(t), t))
            trimmed = list(known)
            trimmed.remove(most_common)
            return " ".join(trimmed)
        return f"{query} attempt-{attempt}"

    def retrieve(self, query: str, *, k: int | None = None) -> RetrievalOutcome:
        """Run the corrective loop for *query*, returning a :class:`RetrievalOutcome`.

        ``corrected`` is True only when at least one rewrite happened *and* the
        final attempt passed the grader. ``budget_exhausted`` is True when the
        step budget cut the loop off before ``max_attempts``. On exhaustion the
        best (last) hits gathered so far are returned rather than discarded.
        """
        top_k = k if k is not None else self._k
        current = query
        queries: list[str] = []
        hits: list[SearchHit] = []
        attempts = 0

        while attempts < self._max_attempts:
            if self._budget is not None and self._budget.check_before_step():
                return RetrievalOutcome(
                    hits=tuple(hits),
                    attempts=attempts,
                    corrected=False,
                    budget_exhausted=True,
                    queries=tuple(queries),
                )
            attempts += 1
            queries.append(current)
            hits = self._retriever.search(current, top_k)
            if self._budget is not None:
                self._budget.record_step()
            if self._grader(current, hits):
                return RetrievalOutcome(
                    hits=tuple(hits),
                    attempts=attempts,
                    corrected=attempts > 1,
                    budget_exhausted=False,
                    queries=tuple(queries),
                )
            if attempts < self._max_attempts:
                current = self._rewriter(current, attempts)

        return RetrievalOutcome(
            hits=tuple(hits),
            attempts=attempts,
            corrected=False,
            budget_exhausted=False,
            queries=tuple(queries),
        )
