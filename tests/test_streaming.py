from mira.core.streaming import (
    Done,
    Error,
    PlanStep,
    Token,
    ToolCall,
    stream,
)


def test_stream_preserves_event_order():
    events = [
        Token(text="Hello"),
        PlanStep(step="search_wells", phase="act"),
        ToolCall(name="get_well", arguments={"well_id": "W-1"}),
        Token(text=" world"),
        Done(correlation_id="corr-123"),
    ]

    result = list(stream(events))

    assert [event.kind for event in result] == [
        "token",
        "plan_step",
        "tool_call",
        "token",
        "done",
    ]
    assert result[0].text == "Hello"
    assert result[1].step == "search_wells"
    assert result[2].name == "get_well"
    assert result[4].correlation_id == "corr-123"


def test_stream_emits_plan_step_event():
    plan = PlanStep(step="reflect", phase="reflect")

    result = list(stream([plan]))

    assert len(result) == 1
    assert isinstance(result[0], PlanStep)
    assert result[0].kind == "plan_step"
    assert result[0].step == "reflect"
    assert result[0].phase == "reflect"


def test_guard_invoked_before_each_chunk():
    events = [
        Token(text="a"),
        PlanStep(step="plan", phase="plan"),
        Error(code="upstream", message="timeout"),
    ]
    guarded: list[str] = []

    def guard(event) -> None:
        guarded.append(event.kind)

    result = list(stream(events, guard=guard))

    assert guarded == ["token", "plan_step", "error"]
    assert [event.kind for event in result] == guarded


def test_default_guard_is_noop():
    events = [Token(text="ok"), Done()]

    assert list(stream(events)) == events


def test_error_event_fields_survive_stream():
    err = Error(code="upstream_timeout", message="MCP call timed out")

    result = list(stream([err]))

    assert len(result) == 1
    assert isinstance(result[0], Error)
    assert result[0].kind == "error"
    assert result[0].code == "upstream_timeout"
    assert result[0].message == "MCP call timed out"
