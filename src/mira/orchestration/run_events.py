"""Runtime/reasoning run → ``StreamEvent`` adapter (e03-f03-t03, ADR-006/009).

Connective tissue between a completed run and the typed event model
(e03-f03-t01) the SSE transport (e03-f03-t02) serializes: turns a run result into
an ``Iterable[StreamEvent]`` so :mod:`mira.app` can serve a run as a
``text/event-stream`` via :func:`mira.core.streaming_sse.make_sse_handler`.

Mapping (see :class:`mira.core.streaming.StreamEvent`): each ``plan_steps`` entry
the reasoning loop (:mod:`mira.orchestration.reasoning`) recorded → one
:class:`~mira.core.streaming.PlanStep` (``phase`` → ``phase``, ``detail`` →
``step``) in recorded order; the run's ``response`` → a single
:class:`~mira.core.streaming.Token` (omitted when empty); then a terminal
:class:`~mira.core.streaming.Done`. A *failed* run — the raised exception, or a
result carrying a truthy ``error`` — is surfaced as one terminal
:class:`~mira.core.streaming.Error` instead of ``Done``, so error shaping lives in
one place and callers only decide *whether* the run failed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from mira.core.streaming import Done, Error, PlanStep, StreamEvent, Token


def run_to_events(result: Mapping[str, Any] | BaseException) -> Iterator[StreamEvent]:
    """Yield the typed event stream for one completed (or failed) run.

    ``result`` is the run's result mapping or the :class:`BaseException` it
    raised. The stream always terminates with exactly one of ``done`` / ``error``.
    """
    if isinstance(result, BaseException):
        yield Error(code="run_failed", message=str(result))
        return

    for entry in result.get("plan_steps") or ():
        yield PlanStep(step=str(entry.get("detail", "")), phase=str(entry.get("phase", "")))

    error = result.get("error")
    if error:
        yield _error(error)
        return

    response = result.get("response")
    if response:
        yield Token(text=str(response))

    correlation_id = result.get("correlation_id")
    yield Done(correlation_id=None if correlation_id is None else str(correlation_id))


def _error(error: Any) -> Error:
    """Build an ``Error`` from a result's ``error`` payload (mapping or string)."""
    if isinstance(error, Mapping):
        return Error(code=str(error.get("code", "run_failed")), message=str(error.get("message", "")))
    return Error(code="run_failed", message=str(error))
