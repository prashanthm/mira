"""Tests for composable middleware pipeline ordering invariants."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mira.core.middleware import (
    AuthError,
    AuthMiddleware,
    Pipeline,
    RequestContext,
)


class RecordingMiddleware:
    """Records stage entry order for assertions."""

    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    async def __call__(self, ctx: RequestContext, call_next: Any) -> Any:
        self._events.append(f"in:{self._name}")
        try:
            result = await call_next()
        except Exception:
            self._events.append(f"out:{self._name}:error")
            raise
        self._events.append(f"out:{self._name}")
        return result


def test_pipeline_runs_stages_in_fixed_order() -> None:
    events: list[str] = []
    pipeline = Pipeline(
        {
            name: RecordingMiddleware(name, events)
            for name in Pipeline.STAGE_ORDER
        }
    )
    ctx = RequestContext()

    async def handler(_ctx: RequestContext) -> str:
        events.append("handler")
        return "ok"

    result = asyncio.run(pipeline.run(ctx, handler))

    assert result == "ok"
    assert events.index("in:auth") == 0
    assert events.index("handler") > events.index("in:guardrail_in")
    assert events.index("out:guardrail_out") > events.index("handler")
    assert events.index("out:telemetry") > events.index("out:guardrail_out")
    assert events[-1] == "out:auth"


def test_auth_failure_never_reaches_handler() -> None:
    events: list[str] = []
    pipeline = Pipeline(
        {
            "auth": AuthMiddleware(allow=lambda _ctx: False),
            "correlation": RecordingMiddleware("correlation", events),
        }
    )
    ctx = RequestContext()

    async def handler(_ctx: RequestContext) -> str:
        events.append("handler")
        return "ok"

    with pytest.raises(AuthError):
        asyncio.run(pipeline.run(ctx, handler))

    assert "handler" not in events
    assert "in:correlation" not in events


def test_guardrail_out_runs_on_handler_error() -> None:
    pipeline = Pipeline()
    ctx = RequestContext()

    async def handler(_ctx: RequestContext) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(pipeline.run(ctx, handler))

    exits = ctx.attributes["guardrail_out_exits"]
    assert len(exits) == 1
    assert isinstance(exits[0], RuntimeError)


def test_guardrail_out_runs_per_stream_chunk() -> None:
    pipeline = Pipeline()
    ctx = RequestContext()

    async def stream() -> AsyncIterator[str]:
        yield "a"
        yield "b"

    async def handler(_ctx: RequestContext) -> AsyncIterator[str]:
        return stream()

    result = asyncio.run(pipeline.run(ctx, handler))
    chunks = asyncio.run(_collect(result))

    assert chunks == ["a", "b"]
    assert ctx.attributes["guardrail_out_exits"] == ["a", "b"]


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [chunk async for chunk in stream]


def test_guardrail_out_runs_on_mid_stream_error() -> None:
    # M1: a mid-iteration failure must still hit guardrail_out, not bypass it.
    pipeline = Pipeline()
    ctx = RequestContext()

    async def stream() -> AsyncIterator[str]:
        yield "a"
        raise RuntimeError("stream boom")

    async def handler(_ctx: RequestContext) -> AsyncIterator[str]:
        return stream()

    async def drive() -> None:
        result = await pipeline.run(ctx, handler)
        async for _ in result:
            pass

    with pytest.raises(RuntimeError, match="stream boom"):
        asyncio.run(drive())

    exits = ctx.attributes["guardrail_out_exits"]
    assert exits[0] == "a"
    assert isinstance(exits[-1], RuntimeError)


def test_compose_order_covers_all_stages() -> None:
    # L1: _COMPOSE_ORDER and STAGE_ORDER must cover the same stages exactly once,
    # so a stage can never be silently dropped/duplicated as the two evolve.
    # (They are not exact reverses: guardrail_out is intentionally bound innermost.)
    from mira.core.middleware import _COMPOSE_ORDER

    assert sorted(_COMPOSE_ORDER) == sorted(Pipeline.STAGE_ORDER)
    assert len(_COMPOSE_ORDER) == len(set(_COMPOSE_ORDER))
    # guardrail_out is innermost; telemetry wraps outside it
    assert _COMPOSE_ORDER.index("guardrail_out") < _COMPOSE_ORDER.index("telemetry")


def test_default_guardrail_stages_are_no_ops() -> None:
    pipeline = Pipeline()
    ctx = RequestContext()

    async def handler(_ctx: RequestContext) -> int:
        return 42

    assert asyncio.run(pipeline.run(ctx, handler)) == 42


def test_stage_order_constant_matches_adr() -> None:
    assert Pipeline.STAGE_ORDER == (
        "auth",
        "correlation",
        "entitlement",
        "guardrail_in",
        "guardrail_out",
        "telemetry",
    )
