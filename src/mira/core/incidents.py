"""Incident detection and remediation-advisory routing (ADR-044).

Turns the AgentOps signals from Phase E into incidents and routes them:

- :class:`IncidentDetector` maps ADR-042 cost anomalies and ADR-043 SLO
  statuses to :class:`Incident` records with a severity classification.
- :class:`IncidentRouter` dispatches incidents through the ADR-039 escalation
  seam — either a :class:`~mira.core.escalation.WebhookNotifier` (or any
  duck-typed notifier with ``.notify(decision, context)``) or a plain
  ``transport`` callable — and keeps an append-only history.

Remediation is advisory only: :func:`remediation_for` names the documented
code-deploy-free lever for each incident kind (ADR-011 budget caps, ADR-012
kill switch/rollback, ADR-046 circuit breaker), attached to the routed payload
as a string for the on-call human. Automatic remediation execution is
deferred — no lever is ever thrown by this module.

No wall clock is baked in: the detector's clock is injected, matching the
ADR-039/ADR-040 seams.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from mira.config.slos import SloStatus
from mira.core.escalation import EscalationAction, EscalationDecision, RiskTier
from mira.model.cost_attribution import Anomaly

Severity = Literal["info", "warning", "critical"]

ClockFn = Callable[[], float]
Transport = Callable[[dict[str, Any]], None]

# Severity -> ADR-039 escalation vocabulary. Critical incidents hold for a
# human decision; warnings notify on-call; info-level incidents proceed.
_SEVERITY_ACTION: dict[Severity, EscalationAction] = {
    "info": "proceed",
    "warning": "notify",
    "critical": "hold_for_approval",
}
_SEVERITY_TIER: dict[Severity, RiskTier] = {
    "info": "low",
    "warning": "medium",
    "critical": "high",
}

# Incident kind -> documented remediation lever (advisory strings only).
_REMEDIATIONS: dict[str, str] = {
    "budget_cap": (
        "Tighten ADR-011 routing budget caps for the breached dimension; if a "
        "specific prompt/tool version is the driver, throw the ADR-012 kill switch."
    ),
    "cost_ceiling": (
        "Review the offending call path against ADR-011 routing budget caps; "
        "throw the ADR-012 kill switch if a prompt/tool version is misrouting cost."
    ),
    "call_rate_spike": (
        "Engage the ADR-046 circuit breaker on the spiking call path to shed load."
    ),
    "slo_burn": (
        "Roll back the most recent prompt/tool promotion via the ADR-012 kill "
        "switch to stop the burn."
    ),
}
_DEFAULT_REMEDIATION = "No mapped lever; follow the on-call runbook for triage."


class Notifier(Protocol):
    """Duck-typed slice of the ADR-039 :class:`WebhookNotifier` this router uses."""

    def notify(
        self,
        decision: EscalationDecision,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver an escalation decision with context."""


@dataclass(frozen=True, slots=True)
class Incident:
    """One detected production incident, in agent terms.

    ``detail`` carries the blast-radius description (dimension, observed vs.
    limit, SLO name, ...); ``created_at`` comes from the detector's injected
    clock — no wall-clock default.
    """

    incident_id: str
    kind: str
    severity: Severity
    source: str
    created_at: float
    detail: dict[str, Any] = field(default_factory=dict)


class IncidentDetector:
    """Maps AgentOps signals to incidents (ADR-044 detection rules).

    Incident ids are derived from an internal sequence (``INC-1``, ``INC-2``,
    ...) unless the caller supplies one; timestamps come from the injected
    ``clock``.
    """

    def __init__(self, *, clock: ClockFn) -> None:
        self._clock = clock
        self._sequence = 0

    def _next_id(self) -> str:
        self._sequence += 1
        return f"INC-{self._sequence}"

    def from_anomalies(
        self,
        anomalies: list[Anomaly],
        *,
        incident_ids: list[str] | None = None,
    ) -> list[Incident]:
        """One incident per ADR-042 anomaly.

        A budget-cap breach means a hard spending limit is already blown —
        critical. A single-span ceiling hit or a call-rate spike is an early
        signature that still needs a human look — warning.
        """
        if incident_ids is not None and len(incident_ids) != len(anomalies):
            raise ValueError("incident_ids must match anomalies one-to-one")
        incidents: list[Incident] = []
        for index, anomaly in enumerate(anomalies):
            severity: Severity = "critical" if anomaly.kind == "budget_cap" else "warning"
            incidents.append(
                Incident(
                    incident_id=(
                        incident_ids[index] if incident_ids is not None else self._next_id()
                    ),
                    kind=anomaly.kind,
                    severity=severity,
                    source="cost_anomaly",
                    created_at=self._clock(),
                    detail={
                        "dimension": anomaly.dimension,
                        "observed": anomaly.observed,
                        "limit": anomaly.limit,
                        "detail": anomaly.detail,
                    },
                )
            )
        return incidents

    def from_slo(
        self,
        status: SloStatus,
        *,
        incident_id: str | None = None,
    ) -> Incident | None:
        """SLO burn to incident: unhealthy is a warning; a fully exhausted
        error budget is critical. Healthy SLOs produce nothing."""
        if status.healthy:
            return None
        severity: Severity = (
            "critical" if status.error_budget_remaining_ratio == 0.0 else "warning"
        )
        return Incident(
            incident_id=incident_id if incident_id is not None else self._next_id(),
            kind="slo_burn",
            severity=severity,
            source="slo_burn",
            created_at=self._clock(),
            detail={
                "slo": status.slo.name,
                "objective": status.slo.objective,
                "achieved_ratio": status.achieved_ratio,
                "error_budget_remaining_ratio": status.error_budget_remaining_ratio,
                "good": status.good,
                "total": status.total,
            },
        )


def remediation_for(incident: Incident) -> str:
    """The documented remediation lever for this incident kind, as an advisory
    string. Never executed here — automatic remediation is deferred."""
    return _REMEDIATIONS.get(incident.kind, _DEFAULT_REMEDIATION)


class IncidentRouter:
    """Dispatches incidents through the ADR-039 notification seam.

    Exactly one delivery path is configured: a ``notifier`` (the Phase-D
    :class:`~mira.core.escalation.WebhookNotifier` or any duck-typed
    equivalent) or a plain ``transport`` callable that receives the full
    incident payload dict. Every routed incident is appended to
    :attr:`history` (append-only; exposed as a tuple).
    """

    def __init__(
        self,
        notifier: Notifier | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        if (notifier is None) == (transport is None):
            raise ValueError("provide exactly one of notifier or transport")
        self._notifier = notifier
        self._transport = transport
        self._history: list[Incident] = []

    @property
    def history(self) -> tuple[Incident, ...]:
        """All routed incidents in dispatch order (append-only)."""
        return tuple(self._history)

    def route(self, incident: Incident) -> dict[str, Any]:
        """Deliver the incident and return the escalation-shaped payload.

        Severity maps onto the ADR-039 vocabulary: critical incidents carry
        ``action="hold_for_approval"`` (a human decides before any lever is
        thrown), warnings ``"notify"``, info ``"proceed"``. The remediation
        string is advisory — routing never executes a lever.
        """
        action = _SEVERITY_ACTION[incident.severity]
        remediation = remediation_for(incident)
        payload: dict[str, Any] = {
            "incident_id": incident.incident_id,
            "kind": incident.kind,
            "severity": incident.severity,
            "source": incident.source,
            "created_at": incident.created_at,
            "detail": dict(incident.detail),
            "action": action,
            "remediation": remediation,
        }

        if self._notifier is not None:
            decision = EscalationDecision(
                action=action,
                tier=_SEVERITY_TIER[incident.severity],
                reasons=(
                    f"{incident.source}: {incident.kind} ({incident.severity})",
                    f"remediation (advisory): {remediation}",
                ),
            )
            self._notifier.notify(decision, {"correlation_id": incident.incident_id})
        else:
            assert self._transport is not None  # constructor invariant
            self._transport(payload)

        self._history.append(incident)
        return payload


__all__ = [
    "ClockFn",
    "Incident",
    "IncidentDetector",
    "IncidentRouter",
    "Notifier",
    "Severity",
    "Transport",
    "remediation_for",
]
