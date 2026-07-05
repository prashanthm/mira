"""Dynamic workflow composition over discoverable agents (ADR-015).

The :class:`WorkflowComposer` turns one request into a multi-step workflow over
the ADR-035 agent-card registry, executed through the ADR-014 supervisor — no
second control plane: every step runs the same specialist subgraphs, budgets,
and result contract a single-agent dispatch uses.

Composition is **structural and deterministic** (the same discipline as the
supervisor's keyword classifier):

* **Seam split** — the query is split on explicit sequence seams
  (``" and then "``, ``"; "``) into ordered sub-queries; each sub-query is
  classified against the card registry. A sub-query no card matches is kept as
  a **fallback step** (``domain == ""``) so the plan never silently drops work.
* **Parallel fan-out** — a seamless query that strongly matches **multiple**
  cards (>= 1 distinct keyword hit for >= 2 cards) composes one step per matched
  card and executes via :meth:`Supervisor.fan_out`.
* **Sequential piping** — multi-step plans execute in order, each step through
  its composed specialist; the prior step's attributed synthesis line is
  appended to the next step's query as ``[context] ...`` so later steps can
  condition on earlier answers (specialist ``query_inference`` hooks still see
  the original sub-query text first).

Single-step plans delegate wholesale to :meth:`Supervisor.invoke`, so the
composer adds nothing to the single-domain path. Synthesis reuses the
supervisor's per-domain attributed-line style (one ``[domain] {...}`` line per
step, errors kept visible).

A model-driven planner slots in **behind** :meth:`WorkflowComposer.compose`
later (ADR-015 deferred note): the step contract and execution path stay fixed;
only the decomposition heuristic is replaced. The optional
:class:`~mira.tools.skills.SkillsRegistry` is the forward seam for that planner
to compose ADR-032 skills (not just whole specialists) into steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.supervisor import FALLBACK_DOMAIN, Supervisor, _synthesize
from mira.tools.skills import SkillsRegistry

# Explicit sequence seams a caller uses to chain sub-tasks in one request.
_SEAM = re.compile(r"\s+and then\s+|;\s+", re.IGNORECASE)

# Same word shape the card registry's classifier scores against.
_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]*")

# Domain label used in a fallback step's result line, matching the supervisor's
# general-path attribution wording.
_GENERAL_DOMAIN = "general"


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One composed unit of work: target domain, sub-query, and why it was planned.

    ``domain == ""`` marks a fallback step — no card matched the sub-query, and
    execution surfaces it as an unmatched (general) result rather than dropping it.
    """

    domain: str
    query: str
    rationale: str


@dataclass
class ComposedWorkflow:
    """A composed plan plus its executed results and synthesized answer."""

    steps: tuple[WorkflowStep, ...]
    results: list[dict[str, Any]] = field(default_factory=list)
    synthesis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [
                {"domain": s.domain, "query": s.query, "rationale": s.rationale}
                for s in self.steps
            ],
            "results": self.results,
            "synthesis": self.synthesis,
        }


class WorkflowComposer:
    """Compose and execute multi-step workflows over discoverable agents (ADR-015)."""

    def __init__(
        self,
        registry: AgentCardRegistry,
        supervisor: Supervisor,
        skills: SkillsRegistry | None = None,
    ) -> None:
        self._registry = registry
        self._supervisor = supervisor
        # Forward seam (documented above): a future planner composes registered
        # ADR-032 skills into steps; deterministic composition does not consult it.
        self._skills = skills

    def compose(self, query: str) -> tuple[WorkflowStep, ...]:
        """Deterministically decompose ``query`` into ordered workflow steps."""
        parts = [part.strip() for part in _SEAM.split(query) if part.strip()]
        if len(parts) > 1:
            return tuple(self._classify(part) for part in parts)

        # No seam: check for a strong multi-card match → parallel fan-out shape.
        words = set(_WORD.findall(query.lower()))
        hits = [card for card in self._registry.cards() if card.keywords & words]
        if len(hits) >= 2:
            return tuple(
                WorkflowStep(
                    domain=card.name,
                    query=query,
                    rationale=f"parallel fan-out: card {card.name!r} matched keywords "
                    f"{sorted(card.keywords & words)}",
                )
                for card in hits
            )
        return (self._classify(query),)

    def execute(self, query: str, *, thread_id: str) -> ComposedWorkflow:
        """Compose then execute ``query``; single-domain plans delegate to the supervisor."""
        steps = self.compose(query)

        if len(steps) == 1:
            # Single-step plan: the supervisor's classify → dispatch → synthesize
            # path (including its general fallback) is exactly this workflow.
            result = self._supervisor.invoke(query, thread_id=thread_id)
            return ComposedWorkflow(
                steps=steps, results=list(result.results), synthesis=result.synthesis
            )

        if all(step.query == query for step in steps):
            # Parallel shape (whole-query multi-card match): supervisor fan-out.
            result = self._supervisor.fan_out(
                query, [step.domain for step in steps], thread_id=thread_id
            )
            return ComposedWorkflow(
                steps=steps, results=list(result.results), synthesis=result.synthesis
            )

        # Sequential pipeline: each step through its composed specialist, with the
        # prior step's attributed line appended as context to the next sub-query.
        results: list[dict[str, Any]] = []
        context_line = ""
        for step in steps:
            step_query = step.query
            if context_line:
                step_query = f"{step.query}\n[context] {context_line}"
            if step.domain and step.domain != FALLBACK_DOMAIN:
                specialist = self._registry.resolve(step.domain)
                result_dict = specialist.invoke(step_query, thread_id=thread_id).to_dict()
            else:
                result_dict = _fallback_result(step.query)
            results.append(result_dict)
            context_line = _synthesize([result_dict])

        return ComposedWorkflow(steps=steps, results=results, synthesis=_synthesize(results))

    def _classify(self, sub_query: str) -> WorkflowStep:
        """One sub-query → one step via the registry's deterministic matcher."""
        card = self._registry.match(sub_query)
        if card is None:
            return WorkflowStep(
                domain=FALLBACK_DOMAIN,
                query=sub_query,
                rationale="no card matched; kept as fallback step",
            )
        return WorkflowStep(
            domain=card.name,
            query=sub_query,
            rationale=f"card {card.name!r} matched sub-query keywords",
        )


def _fallback_result(sub_query: str) -> dict[str, Any]:
    """Structured result for an unmatched step, in the specialist-result shape."""
    return {
        "domain": _GENERAL_DOMAIN,
        "query": sub_query,
        "answer": {"detail": f"no specialist matched: {sub_query}"},
        "plan_steps": [],
        "bound_exceeded": None,
        "error": None,
    }


__all__ = ["ComposedWorkflow", "WorkflowComposer", "WorkflowStep"]
