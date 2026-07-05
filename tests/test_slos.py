"""Tests for SLOs-as-code and error-budget accounting (ADR-043)."""

from __future__ import annotations

import pytest

from mira.config.slos import (
    DEFAULT_SLOS,
    Slo,
    SloTracker,
    slo_health_payload,
)


def _slo(objective: float = 0.9, window_events: int = 10, name: str = "s") -> Slo:
    return Slo(
        name=name,
        description="test SLO",
        objective=objective,
        window_events=window_events,
    )


# --- Slo validation ---

def test_objective_must_be_in_zero_one_interval() -> None:
    with pytest.raises(ValueError):
        _slo(objective=0.0)
    with pytest.raises(ValueError):
        _slo(objective=1.5)
    _slo(objective=1.0)  # inclusive upper bound is allowed


def test_window_events_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _slo(window_events=0)


# --- ring-buffer windowing ---

def test_window_keeps_only_the_last_n_events() -> None:
    tracker = SloTracker([_slo(objective=0.5, window_events=3)])
    for good in (False, False, False, True, True):
        tracker.record("s", good)

    status = tracker.status("s")
    # Window is the last 3 outcomes: False, True, True.
    assert status.total == 3
    assert status.good == 2
    assert status.error_budget_spent == 1


def test_old_failures_age_out_of_the_window() -> None:
    tracker = SloTracker([_slo(objective=0.9, window_events=2)])
    tracker.record("s", False)
    assert not tracker.status("s").healthy

    tracker.record("s", True)
    tracker.record("s", True)  # the failure has slid out
    status = tracker.status("s")
    assert status.total == 2
    assert status.healthy


def test_unknown_slo_name_raises() -> None:
    tracker = SloTracker([_slo()])
    with pytest.raises(KeyError):
        tracker.record("nope", True)
    with pytest.raises(KeyError):
        tracker.status("nope")


# --- error-budget math edge cases ---

def test_zero_events_is_vacuously_healthy() -> None:
    tracker = SloTracker([_slo(objective=0.99)])
    status = tracker.status("s")
    assert status.total == 0
    assert status.good == 0
    assert status.achieved_ratio == 1.0
    assert status.error_budget_total == 0.0
    assert status.error_budget_spent == 0
    assert status.error_budget_remaining_ratio == 1.0
    assert status.healthy


def test_exactly_at_objective_is_healthy() -> None:
    tracker = SloTracker([_slo(objective=0.9, window_events=10)])
    for good in [True] * 9 + [False]:
        tracker.record("s", good)

    status = tracker.status("s")
    assert status.achieved_ratio == pytest.approx(0.9)
    assert status.healthy  # achieved_ratio >= objective
    assert status.error_budget_total == pytest.approx(1.0)
    assert status.error_budget_spent == 1
    assert status.error_budget_remaining_ratio == 0.0


def test_budget_exhausted_clamps_remaining_ratio_at_zero() -> None:
    tracker = SloTracker([_slo(objective=0.9, window_events=10)])
    for good in [True] * 5 + [False] * 5:
        tracker.record("s", good)

    status = tracker.status("s")
    assert not status.healthy
    assert status.error_budget_spent == 5
    assert status.error_budget_remaining_ratio == 0.0  # clamped, never negative


def test_perfect_objective_with_one_failure_exhausts_zero_budget() -> None:
    # objective=1.0 -> error_budget_total == 0; any failure spends it all.
    tracker = SloTracker([_slo(objective=1.0, window_events=5)])
    tracker.record("s", True)
    assert tracker.status("s").error_budget_remaining_ratio == 1.0

    tracker.record("s", False)
    status = tracker.status("s")
    assert not status.healthy
    assert status.error_budget_remaining_ratio == 0.0


def test_all_good_leaves_full_budget() -> None:
    tracker = SloTracker([_slo(objective=0.9, window_events=10)])
    for _ in range(10):
        tracker.record("s", True)

    status = tracker.status("s")
    assert status.healthy
    assert status.error_budget_spent == 0
    assert status.error_budget_remaining_ratio == 1.0


# --- DEFAULT_SLOS shape ---

def test_default_slos_are_the_documented_reference_set() -> None:
    by_name = {slo.name: slo for slo in DEFAULT_SLOS}
    assert set(by_name) == {
        "turn-success",
        "turn-latency-under-budget",
        "eval-gate-pass",
    }
    assert by_name["turn-success"].objective == 0.99
    assert by_name["turn-latency-under-budget"].objective == 0.95
    assert by_name["eval-gate-pass"].objective == 0.99
    for slo in DEFAULT_SLOS:
        assert 0.0 < slo.objective <= 1.0
        assert slo.window_events >= 1
        assert slo.description


def test_tracker_defaults_to_default_slos() -> None:
    tracker = SloTracker()
    assert {slo.name for slo in tracker.slos} == {slo.name for slo in DEFAULT_SLOS}
    # All start vacuously healthy.
    assert all(tracker.status(slo.name).healthy for slo in DEFAULT_SLOS)


# --- health payload ---

def test_health_payload_is_json_safe_summary_per_slo() -> None:
    import json

    tracker = SloTracker([_slo(objective=0.9, window_events=4, name="turns")])
    tracker.record("turns", True)
    tracker.record("turns", False)

    payload = slo_health_payload(tracker)

    assert set(payload) == {"turns"}
    entry = payload["turns"]
    assert entry["objective"] == 0.9
    assert entry["window_events"] == 4
    assert entry["good"] == 1
    assert entry["total"] == 2
    assert entry["achieved_ratio"] == pytest.approx(0.5)
    assert entry["healthy"] is False
    json.dumps(payload)  # must be JSON-serializable for /health
