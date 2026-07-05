import json

import pytest

from mira.core.streaming import Done, Error, PlanStep, Token, ToolCall
from mira.core.streaming_sse import (
    CONTENT_TYPE,
    format_event,
    make_sse_handler,
    sse_frames,
    sse_response,
)


def _parse_frame(frame: str) -> tuple[str, dict]:
    """Split a single SSE frame into (event_name, data_dict)."""
    lines = frame.split("\n")
    assert lines[-2:] == ["", ""], "frame must end with a blank line"
    event_line, data_line = lines[0], lines[1]
    assert event_line.startswith("event: ")
    assert data_line.startswith("data: ")
    return event_line[len("event: ") :], json.loads(data_line[len("data: ") :])


def test_format_event_emits_event_and_data_lines():
    frame = format_event(Token(text="Hello"))

    name, data = _parse_frame(frame)
    assert name == "token"
    assert data == {"text": "Hello"}
    assert "kind" not in data  # kind is the SSE event name, not a data field


def test_format_event_serializes_all_event_types():
    frames = {
        "plan_step": format_event(PlanStep(step="search_wells", phase="act")),
        "tool_call": format_event(ToolCall(name="get_well", arguments={"well_id": "W-1"})),
        "done": format_event(Done(correlation_id="corr-123")),
        "error": format_event(Error(code="upstream", message="timeout")),
    }

    name, data = _parse_frame(frames["plan_step"])
    assert (name, data) == ("plan_step", {"step": "search_wells", "phase": "act"})

    name, data = _parse_frame(frames["tool_call"])
    assert name == "tool_call"
    assert data == {"name": "get_well", "arguments": {"well_id": "W-1"}}

    name, data = _parse_frame(frames["done"])
    assert (name, data) == ("done", {"correlation_id": "corr-123"})

    name, data = _parse_frame(frames["error"])
    assert (name, data) == ("error", {"code": "upstream", "message": "timeout"})


def test_sse_frames_preserve_event_order():
    events = [
        Token(text="Hello"),
        PlanStep(step="search_wells", phase="act"),
        ToolCall(name="get_well", arguments={"well_id": "W-1"}),
        Token(text=" world"),
        Done(correlation_id="corr-123"),
    ]

    names = [_parse_frame(frame)[0] for frame in sse_frames(events)]

    assert names == ["token", "plan_step", "tool_call", "token", "done"]


def test_done_terminates_the_stream():
    events = [Token(text="a"), Done()]

    frames = list(sse_frames(events))

    assert len(frames) == 2
    assert _parse_frame(frames[-1])[0] == "done"


def test_error_terminates_the_stream():
    events = [Token(text="a"), Error(code="upstream_timeout", message="MCP call timed out")]

    frames = list(sse_frames(events))

    assert len(frames) == 2
    name, data = _parse_frame(frames[-1])
    assert name == "error"
    assert data == {"code": "upstream_timeout", "message": "MCP call timed out"}


def test_guard_runs_before_each_frame_is_emitted():
    events = [Token(text="a"), PlanStep(step="plan", phase="plan"), Done()]
    guarded: list[str] = []

    def guard(event) -> None:
        guarded.append(event.kind)

    names = [_parse_frame(frame)[0] for frame in sse_frames(events, guard=guard)]

    assert guarded == ["token", "plan_step", "done"]
    assert names == guarded


def test_raising_guard_aborts_before_offending_frame_is_emitted():
    events = [Token(text="ok"), Token(text="blocked"), Done()]
    emitted: list[str] = []

    def guard(event) -> None:
        if getattr(event, "text", None) == "blocked":
            raise ValueError("guardrail-out blocked this chunk")

    generator = sse_frames(events, guard=guard)

    # First (allowed) frame is produced...
    first = next(generator)
    emitted.append(_parse_frame(first)[1]["text"])

    # ...then the guard raises on the second chunk *before* it is formatted/emitted.
    with pytest.raises(ValueError, match="guardrail-out"):
        next(generator)

    assert emitted == ["ok"]


def test_default_guard_is_noop():
    events = [Token(text="ok"), Done()]

    frames = list(sse_frames(events))

    assert [_parse_frame(f)[0] for f in frames] == ["token", "done"]


def test_sse_response_yields_utf8_bytes():
    chunks = list(sse_response([Token(text="café")]))

    assert all(isinstance(chunk, bytes) for chunk in chunks)
    assert chunks[0] == format_event(Token(text="café")).encode("utf-8")


def test_handler_sets_event_stream_content_type():
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    handler = make_sse_handler([Token(text="a"), Done()])
    body = handler({}, start_response)

    assert captured["status"] == "200 OK"
    assert captured["headers"]["Content-Type"] == CONTENT_TYPE

    frames = [chunk.decode("utf-8") for chunk in body]
    assert [_parse_frame(f)[0] for f in frames] == ["token", "done"]


def test_handler_body_is_streamed_not_buffered():
    consumed: list[str] = []

    def producer():
        consumed.append("token")
        yield Token(text="a")
        consumed.append("done")
        yield Done()

    handler = make_sse_handler(producer())
    body = handler({}, lambda status, headers: None)

    # Nothing is consumed from the producer until the WSGI body is iterated.
    assert consumed == []
    body_iter = iter(body)
    first = next(body_iter)
    assert _parse_frame(first.decode("utf-8"))[0] == "token"
    assert consumed == ["token"]
