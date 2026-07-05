"""Streaming event model and guarded stream generator (ADR-006/009)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

OutputGuard = Callable[["StreamEvent"], None]


def _noop_guard(_event: StreamEvent) -> None:
    pass


@dataclass(frozen=True)
class Token:
    kind: Literal["token"] = "token"
    text: str = ""


@dataclass(frozen=True)
class PlanStep:
    kind: Literal["plan_step"] = "plan_step"
    step: str = ""
    phase: str = ""


@dataclass(frozen=True)
class ToolCall:
    kind: Literal["tool_call"] = "tool_call"
    name: str = ""
    arguments: dict[str, Any] | None = None


@dataclass(frozen=True)
class Done:
    kind: Literal["done"] = "done"
    correlation_id: str | None = None


@dataclass(frozen=True)
class Error:
    kind: Literal["error"] = "error"
    code: str = ""
    message: str = ""


StreamEvent = Token | PlanStep | ToolCall | Done | Error


def stream(
    events: Iterable[StreamEvent],
    guard: OutputGuard | None = None,
) -> Iterator[StreamEvent]:
    """Yield stream events, invoking the output guard before each chunk leaves.

    If ``guard`` raises, the generator stops without yielding the current event
    (the exception propagates to the caller and aborts the iterator mid-stream).
    """
    output_guard = guard or _noop_guard
    for event in events:
        output_guard(event)
        yield event
