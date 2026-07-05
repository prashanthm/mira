"""Risk-tiered HITL escalation policy and notification seam (ADR-039).

Classifies a proposed action into a risk tier from structural signals only
(ADR-031 contract annotations, guardrail findings, budget consumption), maps
the tier to an escalation decision, and posts decisions through an injectable
webhook transport. The reasoning loop's ``require_hitl`` / ``interrupt()`` gate
(ADR-013) is the enforcement point for ``hold_for_approval`` decisions; the
:class:`WebhookNotifier` is the seam Phase-E incident routing reuses.

No wall clock or network is baked in — the notifier's transport and clock are
injected.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from mira.core.guardrails import ViolationFinding
from mira.tools.contract import ToolContract, ToolValidationError, validate_input

RiskTier = Literal["low", "medium", "high"]
EscalationAction = Literal["proceed", "notify", "hold_for_approval"]

# Budget consumption at or above this fraction of the ceiling is medium risk.
DEFAULT_BUDGET_THRESHOLD = 0.8


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Structural facts about a proposed action, gathered by the caller.

    ``budget_fraction`` is consumed/ceiling for the dominant budget dimension
    (cost or steps) — the caller computes it from :class:`ReasoningBudget`
    state so this module stays orchestration-free.
    """

    tool_name: str | None = None
    args: Mapping[str, Any] | None = None
    injection_findings: tuple[ViolationFinding, ...] = ()
    budget_fraction: float | None = None


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Tier plus the structural reasons that produced it."""

    tier: RiskTier
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    """What happens to the action: proceed, notify, or hold for approval."""

    action: EscalationAction
    tier: RiskTier
    reasons: tuple[str, ...] = ()

    @property
    def require_hitl(self) -> bool:
        """True when the reasoning loop must gate on ``interrupt()`` (ADR-013)."""
        return self.action == "hold_for_approval"


class RiskPolicy:
    """Classifies a proposed action into a risk tier (ADR-039 policy model).

    High: destructive contract, matched injection finding, unknown tool, or
    out-of-contract arguments. Medium: budget consumption at/above the
    threshold fraction. Low: everything else.
    """

    def __init__(
        self,
        contracts: Mapping[str, ToolContract] | None = None,
        *,
        budget_threshold: float = DEFAULT_BUDGET_THRESHOLD,
    ) -> None:
        self._contracts = dict(contracts or {})
        self._budget_threshold = budget_threshold

    def assess(self, action_context: ActionContext) -> RiskAssessment:
        reasons: list[str] = []

        if action_context.injection_findings:
            codes = ", ".join(f.code for f in action_context.injection_findings)
            reasons.append(f"injection finding matched ({codes})")

        contract: ToolContract | None = None
        if action_context.tool_name is not None:
            contract = self._contracts.get(action_context.tool_name)
            if contract is None:
                reasons.append(f"unknown tool {action_context.tool_name!r}")
            else:
                if contract.destructiveHint:
                    reasons.append(
                        f"tool {action_context.tool_name!r} carries destructiveHint"
                    )
                try:
                    validate_input(contract, dict(action_context.args or {}))
                except ToolValidationError as exc:
                    reasons.append(f"args out of contract: {exc.message}")

        if reasons:
            return RiskAssessment(tier="high", reasons=tuple(reasons))

        fraction = action_context.budget_fraction
        if fraction is not None and fraction >= self._budget_threshold:
            return RiskAssessment(
                tier="medium",
                reasons=(
                    f"budget consumption {fraction:.2f} >= "
                    f"threshold {self._budget_threshold:.2f}",
                ),
            )

        return RiskAssessment(tier="low", reasons=())


class EscalationPolicy:
    """Maps a risk tier to an escalation decision (ADR-039).

    High requires HITL (``hold_for_approval`` → ``require_hitl=True`` for the
    reasoning loop / a pipeline reject), medium notifies, low proceeds.
    """

    _ACTIONS: dict[RiskTier, EscalationAction] = {
        "low": "proceed",
        "medium": "notify",
        "high": "hold_for_approval",
    }

    def decide(self, assessment: RiskAssessment) -> EscalationDecision:
        return EscalationDecision(
            action=self._ACTIONS[assessment.tier],
            tier=assessment.tier,
            reasons=assessment.reasons,
        )


class WebhookNotifier:
    """Async-free webhook seam: posts escalation payloads through an injected
    transport (ADR-039 mechanism; Phase-E incident routing reuses this seam).

    The default transport appends to the in-memory ``sent`` list. A timestamp
    is included only when an injectable ``clock`` is supplied — no wall clock
    by default.
    """

    def __init__(
        self,
        transport: Callable[[dict[str, Any]], None] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self._transport = transport if transport is not None else self.sent.append
        self._clock = clock

    def notify(
        self,
        decision: EscalationDecision,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = dict(context or {})
        payload: dict[str, Any] = {
            "tier": decision.tier,
            "action": decision.action,
            "reasons": list(decision.reasons),
            "correlation_id": str(ctx.get("correlation_id", "")),
        }
        if self._clock is not None:
            payload["timestamp"] = self._clock()
        self._transport(payload)
        return payload


__all__ = [
    "DEFAULT_BUDGET_THRESHOLD",
    "ActionContext",
    "EscalationAction",
    "EscalationDecision",
    "EscalationPolicy",
    "RiskAssessment",
    "RiskPolicy",
    "RiskTier",
    "WebhookNotifier",
]
