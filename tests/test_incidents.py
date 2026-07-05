"""Tests for incident detection and remediation-advisory routing (ADR-044)."""

from __future__ import annotations

import pytest

from mira.config.slos import Slo, SloStatus, SloTracker
from mira.core.escalation import WebhookNotifier
from mira.core.incidents import (
    Incident,
    IncidentDetector,
    IncidentRouter,
    remediation_for,
)
from mira.model.cost_attribution import Anomaly


def _clock(start: float = 100.0):
    state = {"now": start}

    def tick() -> float:
        state["now"] += 1.0
        return state["now"]

    return tick


def _anomaly(kind: str, dimension: str = "tenant:t1") -> Anomaly:
    return Anomaly(
        kind=kind,  # type: ignore[arg-type]
        dimension=dimension,
        observed=10.0,
        limit=5.0,
        detail=f"{kind} over {dimension}",
    )


def _burned_slo_status(*, exhausted: bool):
    """An unhealthy SloStatus; fully exhausted budget when ``exhausted``.

    With the ADR-043 window accounting, any tracker-derived unhealthy status
    has already exhausted its budget (spent > (1-objective)*total by
    definition), so the not-exhausted warning case is built directly — the
    detector consumes any SloStatus, e.g. from differently scoped accounting.
    """
    if exhausted:
        tracker = SloTracker([Slo("s", "test", objective=0.9, window_events=10)])
        for _ in range(10):
            tracker.record("s", False)
        status = tracker.status("s")
    else:
        status = SloStatus(
            slo=Slo("s", "test", objective=0.9, window_events=10),
            good=8,
            total=10,
            achieved_ratio=0.8,
            error_budget_total=4.0,  # wider budget scope than the window
            error_budget_spent=2,
            error_budget_remaining_ratio=0.5,
            healthy=False,
        )
    assert not status.healthy
    assert (status.error_budget_remaining_ratio == 0.0) == exhausted
    return status


def _incident(kind: str = "budget_cap", severity: str = "critical") -> Incident:
    return Incident(
        incident_id="INC-X",
        kind=kind,
        severity=severity,  # type: ignore[arg-type]
        source="cost_anomaly",
        created_at=1.0,
    )


# --- IncidentDetector.from_anomalies ---

def test_budget_cap_anomaly_maps_to_critical() -> None:
    detector = IncidentDetector(clock=_clock())
    (incident,) = detector.from_anomalies([_anomaly("budget_cap")])
    assert incident.severity == "critical"
    assert incident.kind == "budget_cap"
    assert incident.source == "cost_anomaly"
    assert incident.detail["dimension"] == "tenant:t1"
    assert incident.detail["observed"] == 10.0
    assert incident.detail["limit"] == 5.0


def test_ceiling_and_spike_anomalies_map_to_warning() -> None:
    detector = IncidentDetector(clock=_clock())
    incidents = detector.from_anomalies(
        [_anomaly("cost_ceiling", "span"), _anomaly("call_rate_spike", "window")]
    )
    assert [i.severity for i in incidents] == ["warning", "warning"]
    assert [i.kind for i in incidents] == ["cost_ceiling", "call_rate_spike"]


def test_incident_ids_derive_from_sequence_and_clock_is_injected() -> None:
    detector = IncidentDetector(clock=_clock(start=100.0))
    first, second = detector.from_anomalies(
        [_anomaly("budget_cap"), _anomaly("cost_ceiling")]
    )
    assert first.incident_id == "INC-1"
    assert second.incident_id == "INC-2"
    assert first.created_at == 101.0
    assert second.created_at == 102.0


def test_caller_supplied_incident_ids_are_used() -> None:
    detector = IncidentDetector(clock=_clock())
    (incident,) = detector.from_anomalies(
        [_anomaly("budget_cap")], incident_ids=["OPS-7"]
    )
    assert incident.incident_id == "OPS-7"

    with pytest.raises(ValueError):
        detector.from_anomalies([_anomaly("budget_cap")], incident_ids=["a", "b"])


def test_no_anomalies_no_incidents() -> None:
    detector = IncidentDetector(clock=_clock())
    assert detector.from_anomalies([]) == []


# --- IncidentDetector.from_slo ---

def test_healthy_slo_produces_no_incident() -> None:
    tracker = SloTracker([Slo("s", "test", objective=0.5, window_events=4)])
    tracker.record("s", True)
    detector = IncidentDetector(clock=_clock())
    assert detector.from_slo(tracker.status("s")) is None


def test_unhealthy_slo_is_warning() -> None:
    detector = IncidentDetector(clock=_clock())
    incident = detector.from_slo(_burned_slo_status(exhausted=False))
    assert incident is not None
    assert incident.severity == "warning"
    assert incident.kind == "slo_burn"
    assert incident.source == "slo_burn"
    assert incident.detail["slo"] == "s"


def test_exhausted_error_budget_is_critical() -> None:
    detector = IncidentDetector(clock=_clock())
    incident = detector.from_slo(_burned_slo_status(exhausted=True))
    assert incident is not None
    assert incident.severity == "critical"
    assert incident.detail["error_budget_remaining_ratio"] == 0.0


# --- remediation advisories ---

def test_remediation_maps_kinds_to_documented_levers() -> None:
    assert "ADR-011" in remediation_for(_incident(kind="budget_cap"))
    assert "ADR-012" in remediation_for(_incident(kind="budget_cap"))
    assert "ADR-011" in remediation_for(_incident(kind="cost_ceiling"))
    assert "ADR-046" in remediation_for(_incident(kind="call_rate_spike"))
    assert "circuit breaker" in remediation_for(_incident(kind="call_rate_spike"))
    assert "ADR-012" in remediation_for(_incident(kind="slo_burn"))
    assert "runbook" in remediation_for(_incident(kind="something_new"))


# --- IncidentRouter ---

def test_router_requires_exactly_one_delivery_path() -> None:
    with pytest.raises(ValueError):
        IncidentRouter()
    with pytest.raises(ValueError):
        IncidentRouter(WebhookNotifier(), transport=lambda payload: None)


def test_critical_incident_routes_hold_for_approval_payload() -> None:
    delivered: list[dict] = []
    router = IncidentRouter(transport=delivered.append)

    payload = router.route(_incident(kind="budget_cap", severity="critical"))

    assert delivered == [payload]
    assert payload["action"] == "hold_for_approval"
    assert payload["severity"] == "critical"
    assert payload["incident_id"] == "INC-X"
    assert "ADR-011" in payload["remediation"]  # advisory string, never executed


def test_warning_incident_routes_notify_and_info_proceeds() -> None:
    delivered: list[dict] = []
    router = IncidentRouter(transport=delivered.append)

    warn = router.route(_incident(kind="cost_ceiling", severity="warning"))
    info = router.route(_incident(kind="cost_ceiling", severity="info"))

    assert warn["action"] == "notify"
    assert info["action"] == "proceed"
    assert len(delivered) == 2


def test_router_through_phase_d_webhook_notifier() -> None:
    notifier = WebhookNotifier()  # default transport collects into .sent
    router = IncidentRouter(notifier)

    incident = _incident(kind="budget_cap", severity="critical")
    router.route(incident)

    (sent,) = notifier.sent
    assert sent["action"] == "hold_for_approval"
    assert sent["tier"] == "high"
    assert sent["correlation_id"] == "INC-X"
    assert any("budget_cap" in reason for reason in sent["reasons"])
    assert any("advisory" in reason for reason in sent["reasons"])


def test_history_is_append_only_and_ordered() -> None:
    router = IncidentRouter(transport=lambda payload: None)
    first = _incident(kind="budget_cap", severity="critical")
    second = _incident(kind="slo_burn", severity="warning")

    assert router.history == ()
    router.route(first)
    snapshot = router.history
    router.route(second)

    assert router.history == (first, second)
    assert snapshot == (first,)  # earlier snapshot unaffected (append-only view)
    with pytest.raises(AttributeError):
        router.history = ()  # type: ignore[misc]


def test_detector_to_router_end_to_end() -> None:
    # Signals -> incidents -> routed payloads with advisory remediation.
    detector = IncidentDetector(clock=_clock())
    delivered: list[dict] = []
    router = IncidentRouter(transport=delivered.append)

    incidents = detector.from_anomalies(
        [_anomaly("budget_cap"), _anomaly("call_rate_spike", "window")]
    )
    slo_incident = detector.from_slo(_burned_slo_status(exhausted=True))
    assert slo_incident is not None
    for incident in [*incidents, slo_incident]:
        router.route(incident)

    assert [p["action"] for p in delivered] == [
        "hold_for_approval",
        "notify",
        "hold_for_approval",
    ]
    assert len(router.history) == 3
