"""Tests for mira_contracts.trace (ADR-049)."""

from __future__ import annotations

import pytest

from mira_contracts.trace import (
    TRACE_VERSION,
    AgentRef,
    BudgetConsumed,
    ContractViolation,
    CostRecord,
    Decision,
    TraceEvent,
    TraceResult,
    validate_trace,
)


def _full_trace() -> TraceResult:
    return TraceResult(
        task_id="research:golden-1",
        correlation_id="corr-1",
        agent=AgentRef(name="foreign-echo", kind="foreign", version="1"),
        status="ok",
        answer={
            "echo": "middleware",
            "provenance": {"source_type": "foreign-echo.stub", "source_id": "t1"},
        },
        events=(
            TraceEvent(phase="plan", detail="plan-1:middleware", index=0),
            TraceEvent(phase="act", detail="act:plan-1", index=1),
            TraceEvent(phase="observe", detail="observed", index=2),
        ),
        decisions=(Decision(kind="routing", detail={"domain": "foreign-echo"}),),
        costs=(
            CostRecord(
                provider="stub",
                model="echo",
                cost=0.0,
                latency_ms=1.0,
                self_reported=True,
            ),
        ),
        budget_consumed=BudgetConsumed(steps=1, tokens=3, seconds=0.1, cost=0.0),
    )


def test_round_trip_full_trace():
    trace = _full_trace()
    assert TraceResult.from_dict(trace.to_dict()) == trace


def test_round_trip_error_and_bound_variants():
    error = TraceResult(
        task_id="t1",
        agent=AgentRef(name="a", kind="specialist"),
        status="error",
        error={"code": "boom", "message": "it broke"},
    )
    bound = TraceResult(
        task_id="t2",
        agent=AgentRef(name="a", kind="foreign"),
        status="bound_exceeded",
        bound_exceeded={"kind": "steps", "limit": 0, "observed": 0, "message": "step limit"},
    )
    for trace in (error, bound):
        assert TraceResult.from_dict(trace.to_dict()) == trace
        assert validate_trace(trace.to_dict()) == trace


def test_events_are_byte_compatible_with_plan_steps():
    # The exact dict shape ReasoningLoop._emit produces (ADR-049 deliberate compat).
    event = TraceEvent(phase="plan", detail="plan-1:q", index=0)
    assert event.to_dict() == {
        "event": "plan_step",
        "phase": "plan",
        "detail": "plan-1:q",
        "index": 0,
    }


def test_validate_accepts_full_trace():
    trace = _full_trace()
    assert validate_trace(trace.to_dict()) == trace
    assert trace.trace_version == TRACE_VERSION


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("trace_version"),
        lambda d: d.update(trace_version="0"),
        lambda d: d.pop("agent"),
        lambda d: d.update(status="unknown"),
        lambda d: d.update(agent={"name": "a", "kind": "alien"}),
        lambda d: d.update(unexpected=True),
        lambda d: d.update(costs=[{"provider": "p", "model": "m", "cost": 0.0}]),
        lambda d: d.update(error={"code": "x"}),
        lambda d: d.update(bound_exceeded={"kind": "steps"}),
    ],
    ids=[
        "missing-version",
        "wrong-version",
        "missing-agent",
        "unknown-status",
        "unknown-agent-kind",
        "extra-key",
        "cost-missing-self-reported",
        "error-missing-message",
        "bound-missing-fields",
    ],
)
def test_validation_is_fail_closed(mutate):
    doc = _full_trace().to_dict()
    mutate(doc)
    with pytest.raises(ContractViolation):
        validate_trace(doc)
