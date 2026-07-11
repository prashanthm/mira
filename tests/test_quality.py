"""Tests for the model-tier escalation trigger (ADR-052)."""

from __future__ import annotations

from mira_harness.quality import (
    BOUND_EXCEEDED_REASON,
    LOW_TRACE_SCORE_REASON,
    UNGROUNDED_REASON,
    EscalationTrigger,
)

GROUNDED_ANSWER = {
    "value": 1,
    "provenance": {"source_type": "docs.section", "source_id": "handbook#x"},
}
PLAN = [{"event": "plan_step", "phase": "plan", "detail": "p", "index": 0}]


def _result(**overrides):
    base = {
        "domain": "research",
        "query": "q",
        "answer": dict(GROUNDED_ANSWER),
        "plan_steps": list(PLAN),
        "bound_exceeded": None,
        "error": None,
        "decisions": [],
    }
    base.update(overrides)
    return base


def test_structurally_good_result_does_not_trigger():
    assert EscalationTrigger().check(_result()) is None


def test_ungrounded_answer_triggers():
    assert (
        EscalationTrigger().check(_result(answer={"value": 1}))
        == UNGROUNDED_REASON
    )


def test_bound_exceeded_triggers():
    result = _result(
        bound_exceeded={"kind": "steps", "limit": 1, "observed": 1, "message": "m"}
    )
    assert EscalationTrigger().check(result) == BOUND_EXCEEDED_REASON


def test_low_trace_score_triggers():
    # No plan steps: score 3/4 = 0.75 < default threshold? 0.75 is not < 0.75 —
    # use a stricter trigger to pin the comparison direction.
    result = _result(plan_steps=[])
    assert EscalationTrigger().check(result) is None  # 0.75 meets the default bar
    assert (
        EscalationTrigger(min_trace_score=0.9).check(result) == LOW_TRACE_SCORE_REASON
    )


def test_error_results_do_not_trigger_on_groundedness():
    """Error results assert no claims (checker semantics) and stay error-handled
    elsewhere; the trigger fires only on the trace-score dimension."""
    result = _result(answer={}, error="boom")
    assert EscalationTrigger(min_trace_score=0.9).check(result) == LOW_TRACE_SCORE_REASON


def test_foreign_trace_shape_parity():
    """The byte-compatible foreign shape (answer/plan_steps/bound_exceeded/error)
    triggers identically."""
    foreign = {
        "answer": {"echo": "x"},  # no provenance
        "plan_steps": list(PLAN),
        "bound_exceeded": None,
        "error": None,
    }
    assert EscalationTrigger().check(foreign) == UNGROUNDED_REASON
