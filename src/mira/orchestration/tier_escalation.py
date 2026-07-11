"""Model-tier escalation wrapper for routable specialists (ADR-052).

A registration-time decorator in the :class:`ForeignSpecialist` style: run
the inner specialist, and when the result is structurally poor
(:class:`~mira_harness.quality.EscalationTrigger`), retry **exactly once**
on the next tier up, keeping the retry only if its trace score improves.
Budget beats capability: a ``BudgetExceeded`` from the retry keeps the first
result. Every attempt is auditable via a ``kind="escalation"`` decision on
the result (ADR-040/049 vocabulary) and the gateway's per-call cost spans.

Never called plain "escalation" — that word belongs to HITL (ADR-039).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mira_harness.quality import EscalationTrigger
from mira_harness.scoring import score_trace

from mira.model.routing import BudgetExceeded
from mira.model.tiering import TIER_ORDER, next_tier_up
from mira.orchestration.agent_cards import RoutableAgent
from mira.orchestration.specialist_scaffold import SpecialistResult

MODEL_TIER_CONTEXT_KEY = "model_tier"


def _decision(
    trigger_reason: str,
    *,
    escalated: bool,
    from_tier: str,
    to_tier: str | None,
    improved: bool | None = None,
    detail: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "trigger": trigger_reason,
        "escalated": escalated,
        "from_tier": from_tier,
        "to_tier": to_tier or "",
    }
    if improved is not None:
        payload["improved"] = improved
    if detail:
        payload["detail"] = detail
    return {"kind": "escalation", "detail": payload}


class TierEscalatingSpecialist:
    """A :class:`RoutableAgent` that retries once on a stronger model tier."""

    def __init__(
        self,
        inner: RoutableAgent,
        *,
        trigger: EscalationTrigger | None = None,
        start_tier: str = "light",
        tiers: Sequence[str] = TIER_ORDER,
    ) -> None:
        self._inner = inner
        self._trigger = trigger if trigger is not None else EscalationTrigger()
        self._start_tier = start_tier
        self._tiers = tuple(tiers)

    def invoke(
        self,
        query: str,
        *,
        thread_id: str,
        context: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> SpecialistResult:
        first = self._inner.invoke(
            query, thread_id=thread_id, context=context, **kwargs
        )
        reason = self._trigger.check(first.to_dict())
        if reason is None:
            return first

        stronger = next_tier_up(self._start_tier, tiers=self._tiers)
        if stronger is None:
            first.decisions.append(
                _decision(
                    reason,
                    escalated=False,
                    from_tier=self._start_tier,
                    to_tier=None,
                    detail="no stronger tier configured",
                )
            )
            return first

        retry_context = dict(context or {})
        retry_context[MODEL_TIER_CONTEXT_KEY] = stronger
        try:
            # Distinct thread id: the retry must not collide with the first
            # attempt's checkpointer state.
            second = self._inner.invoke(
                query,
                thread_id=f"{thread_id}:tier-escalated",
                context=retry_context,
                **kwargs,
            )
        except BudgetExceeded:
            first.decisions.append(
                _decision(
                    reason,
                    escalated=False,
                    from_tier=self._start_tier,
                    to_tier=stronger,
                    detail="budget",
                )
            )
            return first

        improved = score_trace(second.to_dict()).score > score_trace(first.to_dict()).score
        kept = second if improved else first
        kept.decisions.append(
            _decision(
                reason,
                escalated=True,
                from_tier=self._start_tier,
                to_tier=stronger,
                improved=improved,
            )
        )
        return kept


__all__ = ["MODEL_TIER_CONTEXT_KEY", "TierEscalatingSpecialist"]
