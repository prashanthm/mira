"""Adapter tests for run → StreamEvent mapping (e03-f03-t03).

One ``plan_step`` per recorded reasoning step (in order), the response as a
``token``, a terminal ``done``; failure path (raised exception / error-bearing
result) → terminal ``error``. The raising-guard abort is asserted against the
SSE handler that mounts this adapter, since the guard runs on the wire path.
"""

from __future__ import annotations

import pytest

from mira.core.streaming import Done, Error, PlanStep, Token
from mira.core.streaming_sse import sse_frames
from mira.orchestration.run_events import run_to_events

# Two reasoning steps shaped like reasoning.py's ``plan_steps`` entries.
_STEPS = [
    {"event": "plan_step", "phase": "plan", "detail": "plan-1:hello", "index": 0},
    {"event": "plan_step", "phase": "act", "detail": "act:plan-1:hello", "index": 1},
]


def test_maps_plan_steps_in_order_then_token_then_done() -> None:
    events = list(run_to_events({"plan_steps": _STEPS, "response": "echo:hello"}))

    assert [e.kind for e in events] == ["plan_step", "plan_step", "token", "done"]
    first, second, token, done = events
    assert isinstance(first, PlanStep) and (first.phase, first.step) == ("plan", "plan-1:hello")
    assert (second.phase, second.step) == ("act", "act:plan-1:hello")
    assert isinstance(token, Token) and token.text == "echo:hello"
    assert isinstance(done, Done)


def test_correlation_id_flows_onto_done() -> None:
    events = list(run_to_events({"response": "ok", "correlation_id": "corr-7"}))

    assert isinstance(events[-1], Done) and events[-1].correlation_id == "corr-7"


def test_empty_response_emits_no_token() -> None:
    # A paused/empty run yields plan steps + done but no blank token.
    kinds = [e.kind for e in run_to_events({"plan_steps": _STEPS, "response": ""})]

    assert kinds == ["plan_step", "plan_step", "done"]


def test_raised_exception_maps_to_terminal_error() -> None:
    events = list(run_to_events(RuntimeError("boom")))

    assert len(events) == 1
    assert isinstance(events[0], Error)
    assert (events[0].code, events[0].message) == ("run_failed", "boom")


def test_error_bearing_result_emits_error_after_plan_steps() -> None:
    result = {
        "plan_steps": _STEPS[:1],
        "error": {"code": "upstream_timeout", "message": "MCP call timed out"},
        "response": "should-not-emit",
    }

    events = list(run_to_events(result))

    assert [e.kind for e in events] == ["plan_step", "error"]
    assert isinstance(events[-1], Error)
    assert (events[-1].code, events[-1].message) == ("upstream_timeout", "MCP call timed out")


def test_raising_guard_aborts_before_offending_frame() -> None:
    # Guard runs on the SSE wire path (e03-f03-t02): a guard that raises on the
    # second plan_step aborts the stream before that frame is formatted/emitted.
    def guard(event) -> None:
        if isinstance(event, PlanStep) and event.phase == "act":
            raise RuntimeError("blocked")

    emitted: list[str] = []
    with pytest.raises(RuntimeError, match="blocked"):
        for frame in sse_frames(run_to_events({"plan_steps": _STEPS}), guard=guard):
            emitted.append(frame)

    assert len(emitted) == 1 and emitted[0].startswith("event: plan_step")
