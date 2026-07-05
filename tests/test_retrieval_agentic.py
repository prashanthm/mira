"""Tests for the corrective retrieve → grade → re-query loop (ADR-029).

Covers first-pass acceptance, grader-rejection → rewriter-correction, the
deterministic default rewriter (out-of-vocabulary drop, lowest-idf drop), the
max_attempts bound, and the duck-typed step budget — including compatibility
with the real ADR-013 :class:`ReasoningBudget` without retrieval importing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.connectors.docs import parse_markdown
from mira.orchestration.reasoning import ReasoningBudget
from mira.retrieval.agentic import CorrectiveRetriever, RetrievalOutcome
from mira.retrieval.hybrid import HybridRetriever, index_corpus
from mira.retrieval.inmemory import InMemoryVectorIndex
from mira.retrieval.sparse import Bm25Index

FIXTURE = Path(__file__).parent / "fixtures" / "handbook.md"


def _retriever() -> HybridRetriever:
    retriever = HybridRetriever(InMemoryVectorIndex(), Bm25Index())
    index_corpus(retriever, parse_markdown(FIXTURE.read_text()), source_id="handbook")
    return retriever


def _fail_first_grader():
    calls = {"n": 0}

    def grader(query, hits):
        calls["n"] += 1
        return calls["n"] > 1

    return grader


def test_good_query_passes_on_first_attempt():
    outcome = CorrectiveRetriever(_retriever()).retrieve("middleware ordering chokepoint")
    assert isinstance(outcome, RetrievalOutcome)
    assert outcome.attempts == 1
    assert outcome.corrected is False
    assert outcome.budget_exhausted is False
    assert outcome.hits[0].doc_id == "middleware-ordering"


def test_grader_rejection_triggers_rewrite_and_corrected_outcome():
    corrective = CorrectiveRetriever(_retriever(), grader=_fail_first_grader())
    outcome = corrective.retrieve("middleware ordering chokepoint zzyqx")
    assert outcome.attempts == 2
    assert outcome.corrected is True
    # Default rewriter dropped the out-of-vocabulary token.
    assert outcome.queries == (
        "middleware ordering chokepoint zzyqx",
        "middleware ordering chokepoint",
    )
    assert outcome.hits[0].doc_id == "middleware-ordering"


def test_default_rewriter_drops_lowest_idf_token_when_all_known():
    # "auth" appears in two handbook sections; "middleware"/"ordering" in one:
    # the most common (least discriminating) token is dropped first.
    corrective = CorrectiveRetriever(_retriever(), grader=_fail_first_grader())
    outcome = corrective.retrieve("auth middleware ordering")
    assert outcome.queries == ("auth middleware ordering", "middleware ordering")
    assert outcome.corrected is True


def test_default_rewriter_appends_attempt_marker_when_nothing_droppable():
    corrective = CorrectiveRetriever(
        _retriever(), grader=lambda q, h: False, max_attempts=2
    )
    outcome = corrective.retrieve("middleware")
    assert outcome.queries == ("middleware", "middleware attempt-1")


def test_exhausting_max_attempts_returns_last_hits_uncorrected():
    corrective = CorrectiveRetriever(_retriever(), grader=lambda q, h: False, max_attempts=3)
    outcome = corrective.retrieve("middleware ordering chokepoint")
    assert outcome.attempts == 3
    assert outcome.corrected is False
    assert outcome.budget_exhausted is False
    assert outcome.hits  # best-effort evidence is returned, not discarded


def test_custom_rewriter_hook_is_used():
    corrective = CorrectiveRetriever(
        _retriever(),
        grader=_fail_first_grader(),
        rewriter=lambda query, attempt: "deployment profile env",
    )
    outcome = corrective.retrieve("qzxv wibble")
    assert outcome.queries == ("qzxv wibble", "deployment profile env")
    assert outcome.hits[0].doc_id == "deployment-profiles"


def test_min_top_score_grades_the_fused_score():
    # 2/(60+1) ≈ 0.0328 is the best possible RRF score for rrf_k=60 with two
    # rankers; a threshold above it can never pass, one below it passes on consensus.
    passing = CorrectiveRetriever(_retriever(), min_top_score=0.03)
    assert passing.retrieve("middleware ordering chokepoint").corrected is False
    failing = CorrectiveRetriever(_retriever(), min_top_score=0.1, max_attempts=2)
    outcome = failing.retrieve("middleware ordering chokepoint")
    assert outcome.attempts == 2
    assert outcome.corrected is False


class _CountdownBudget:
    """Duck-typed step budget: allows N steps, then reports exhaustion."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.steps = 0

    def check_before_step(self):
        if self.steps >= self.allowed:
            return {"kind": "steps", "limit": self.allowed}
        return None

    def record_step(self) -> None:
        self.steps += 1


def test_step_budget_exhaustion_cuts_the_loop_off():
    budget = _CountdownBudget(allowed=1)
    corrective = CorrectiveRetriever(
        _retriever(), grader=lambda q, h: False, max_attempts=5, budget=budget
    )
    outcome = corrective.retrieve("middleware ordering chokepoint")
    assert outcome.budget_exhausted is True
    assert outcome.attempts == 1
    assert outcome.hits  # hits gathered before exhaustion are kept
    assert budget.steps == 1


def test_pre_exhausted_budget_returns_before_any_retrieval():
    corrective = CorrectiveRetriever(_retriever(), budget=_CountdownBudget(allowed=0))
    outcome = corrective.retrieve("middleware ordering chokepoint")
    assert outcome.budget_exhausted is True
    assert outcome.attempts == 0
    assert outcome.hits == ()


def test_reasoning_budget_is_duck_type_compatible():
    # The ADR-013 budget object plugs in directly — retrieval never imports it.
    budget = ReasoningBudget(max_steps=1)
    corrective = CorrectiveRetriever(
        _retriever(), grader=lambda q, h: False, max_attempts=5, budget=budget
    )
    outcome = corrective.retrieve("middleware ordering chokepoint")
    assert outcome.budget_exhausted is True
    assert outcome.attempts == 1
    assert budget.steps == 1


def test_invalid_construction_is_rejected():
    with pytest.raises(ValueError):
        CorrectiveRetriever(_retriever(), max_attempts=0)
    with pytest.raises(ValueError):
        CorrectiveRetriever(_retriever(), k=0)
