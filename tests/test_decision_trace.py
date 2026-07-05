"""Tests for the append-only decision-trace audit store (ADR-040)."""

from __future__ import annotations

import dataclasses

import pytest

from mira.core.decision_trace import TracedClaim, TraceStore, uncertainty_for


def _clock(start: float = 100.0):
    state = {"now": start}

    def tick() -> float:
        state["now"] += 1.0
        return state["now"]

    return tick


def _store() -> TraceStore:
    return TraceStore(clock=_clock())


GROUNDED_RESULT = {
    "domain": "research",
    "query": "what does the handbook say about middleware?",
    "answer": {
        "anchor": "#middleware",
        "snippet": "stage order is fixed",
        "provenance": {"source_type": "docs", "source_id": "handbook.md"},
    },
    "plan_steps": [
        {"event": "plan_step", "phase": "plan", "detail": "plan-1", "index": 0},
        {"event": "plan_step", "phase": "observe", "detail": "obs", "index": 1},
    ],
    "bound_exceeded": None,
    "error": None,
}


# --- append-only invariants ---

def test_append_assigns_monotonic_sequence_and_clock() -> None:
    store = _store()
    first = store.append(trace_id="t1", correlation_id="c1", query="q1")
    second = store.append(trace_id="t2", correlation_id="c1", query="q2")

    assert (first.sequence, second.sequence) == (0, 1)
    assert second.created_at > first.created_at


def test_records_are_frozen() -> None:
    store = _store()
    record = store.append(trace_id="t1", correlation_id="c1", query="q")
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.query = "tampered"  # type: ignore[misc]


def test_store_has_no_update_or_delete_surface() -> None:
    public = {name for name in dir(TraceStore) if not name.startswith("_")}
    assert public == {"append", "get", "for_correlation", "all", "record_from_result"}


def test_read_surfaces_return_tuples_and_do_not_leak_internal_state() -> None:
    store = _store()
    store.append(trace_id="t1", correlation_id="c1", query="q")

    snapshot = store.all()
    assert isinstance(snapshot, tuple)
    assert isinstance(store.for_correlation("c1"), tuple)

    # A later append must not mutate an earlier snapshot.
    store.append(trace_id="t2", correlation_id="c1", query="q2")
    assert len(snapshot) == 1
    assert len(store.all()) == 2


def test_get_and_for_correlation() -> None:
    store = _store()
    store.append(trace_id="t1", correlation_id="c1", query="q1")
    store.append(trace_id="t2", correlation_id="c2", query="q2")
    store.append(trace_id="t3", correlation_id="c1", query="q3")

    assert store.get("t2").query == "q2"
    assert store.get("missing") is None
    assert [r.trace_id for r in store.for_correlation("c1")] == ["t1", "t3"]
    assert store.for_correlation("nope") == ()


# --- record_from_result extraction ---

def test_record_from_result_extracts_claims_with_provenance() -> None:
    store = _store()
    record = store.record_from_result("t1", "c1", GROUNDED_RESULT)

    assert record.query == GROUNDED_RESULT["query"]
    assert len(record.claims) == 1
    claim = record.claims[0]
    assert claim.source_type == "docs"
    assert claim.source_id == "handbook.md"
    assert claim.grounded
    assert "stage order is fixed" in claim.statement
    assert len(record.plan_steps) == 2
    assert record.plan_steps[0]["phase"] == "plan"


def test_record_from_result_marks_unattributed_answer_as_ungrounded_claim() -> None:
    store = _store()
    record = store.record_from_result(
        "t1", "c1", {"query": "q", "answer": {"snippet": "no source"}, "plan_steps": []}
    )

    assert len(record.claims) == 1
    assert not record.claims[0].grounded
    assert record.claims[0].source_id == ""


def test_record_from_result_carries_guardrail_findings() -> None:
    store = _store()
    record = store.record_from_result(
        "t1",
        "c1",
        GROUNDED_RESULT,
        guardrail_findings=[{"code": "topic_drift", "snippet": "x"}],
    )
    assert len(record.guardrail_findings) == 1
    assert record.to_dict()["guardrail_findings"][0]["code"] == "topic_drift"


# --- uncertainty (ADR-041) ---

def test_uncertainty_fully_grounded_record() -> None:
    store = _store()
    record = store.record_from_result("t1", "c1", GROUNDED_RESULT)

    uncertainty = uncertainty_for(record)
    assert uncertainty["grounded_claims"] == 1
    assert uncertainty["total_claims"] == 1
    assert uncertainty["grounded_ratio"] == 1.0
    assert uncertainty["missing_provenance"] is False
    assert uncertainty["has_guardrail_findings"] is False
    assert uncertainty["band"] == "supported"


def test_uncertainty_flags_missing_provenance_and_findings() -> None:
    store = _store()
    record = store.append(
        trace_id="t1",
        correlation_id="c1",
        query="q",
        claims=(
            TracedClaim(statement="grounded", source_id="s", source_type="docs"),
            TracedClaim(statement="ungrounded"),
        ),
        guardrail_findings=({"code": "ungrounded_answer"},),
    )

    uncertainty = uncertainty_for(record)
    assert uncertainty["grounded_ratio"] == 0.5
    assert uncertainty["missing_provenance"] is True
    assert uncertainty["has_guardrail_findings"] is True
    assert uncertainty["band"] == "partially_supported"


def test_uncertainty_no_claims_is_unsupported() -> None:
    store = _store()
    record = store.append(trace_id="t1", correlation_id="c1", query="q")
    uncertainty = uncertainty_for(record)
    assert uncertainty["total_claims"] == 0
    assert uncertainty["band"] == "unsupported"
    assert uncertainty["missing_provenance"] is True
