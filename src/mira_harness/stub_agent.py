"""Deterministic offline foreign agent — the ADR-051 experiment's subject.

``StubEchoAgent`` is to foreign agents what the reference agent's ``local``
echo provider is to LLM providers: a fully deterministic, network-free
implementation that exercises every contract seam. It imports
``mira_contracts`` ONLY — that constraint is the agent-agnosticism proof and
is pinned by a test; adding any other import breaks the experiment's premise.

Behavior contract (kept deterministic on purpose so it can sit inside the
golden gate):

- the echoed token is the text after the objective's last ``:`` (else the
  last whitespace-separated word), lowercased and stripped;
- the answer carries the recursive ADR-045 provenance shape so groundedness
  and trace scoring pass;
- one plan/act/observe event triple earns ``has_plan``;
- ``budget_consumed`` is reported honestly (1 step, token count = objective
  word count, zero cost) and a zero-step budget returns
  ``status="bound_exceeded"`` — the budget-conformance probe;
- the single ``CostRecord`` is flagged ``self_reported`` (nothing measured
  it) with zero cost.
"""

from __future__ import annotations

from typing import Any

from mira_contracts.envelope import ExecutionEnvelope
from mira_contracts.trace import (
    AgentRef,
    BudgetConsumed,
    CostRecord,
    TraceEvent,
    TraceResult,
)

AGENT_NAME = "foreign-echo"
SOURCE_TYPE = "foreign-echo.stub"


def _echo_token(objective: str) -> str:
    """Deterministic token extraction: after the last ':', else the last word."""
    text = objective.rsplit(":", 1)[1] if ":" in objective else objective
    words = text.strip().split()
    return words[-1].lower() if words else ""


class StubEchoAgent:
    """An :class:`~mira_contracts.agent.EnvelopeRunner` that echoes, grounded."""

    def card(self) -> dict[str, Any]:
        """A2A-shaped discovery card (the ``AgentCard.to_dict()`` shape)."""
        return {
            "name": AGENT_NAME,
            "description": (
                "Deterministic offline echo agent — the ADR-051 foreign-adapter "
                "experiment subject."
            ),
            "version": "1",
            "capabilities": {
                "tool_prefixes": [f"{AGENT_NAME}."],
                "keywords": ["delegate", "external", "partner", "echo"],
            },
        }

    def run(self, envelope: ExecutionEnvelope) -> TraceResult:
        agent = AgentRef(name=AGENT_NAME, kind="foreign", version="1")
        if envelope.budget.max_steps <= 0:
            return TraceResult(
                task_id=envelope.task_id,
                correlation_id=envelope.correlation_id,
                agent=agent,
                status="bound_exceeded",
                bound_exceeded={
                    "kind": "steps",
                    "limit": float(envelope.budget.max_steps),
                    "observed": 0.0,
                    "message": "step limit reached",
                },
            )

        token = _echo_token(envelope.objective)
        answer = {
            "echo": token,
            "provenance": {"source_type": SOURCE_TYPE, "source_id": envelope.task_id},
        }
        events = (
            TraceEvent(phase="plan", detail=f"plan-1:{envelope.objective}", index=0),
            TraceEvent(phase="act", detail=f"act:echo:{token}", index=1),
            TraceEvent(phase="observe", detail=f"echoed:{token}", index=2),
        )
        return TraceResult(
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            agent=agent,
            status="ok",
            answer=answer,
            events=events,
            costs=(
                CostRecord(
                    provider="stub",
                    model="echo-1",
                    cost=0.0,
                    latency_ms=0.0,
                    self_reported=True,
                ),
            ),
            budget_consumed=BudgetConsumed(
                steps=1,
                tokens=len(envelope.objective.split()),
                seconds=0.0,
                cost=0.0,
            ),
        )


__all__ = ["AGENT_NAME", "SOURCE_TYPE", "StubEchoAgent"]
