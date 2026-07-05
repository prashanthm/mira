"""SSE wire transport for the streaming event model (e03-f03-t02, ADR-006/009).

This is the *transport* layer that e03-f03-t01 left out: it serializes the
existing :class:`~mira.core.streaming.StreamEvent` union to the
``text/event-stream`` wire format and exposes a WSGI handler the e03-f07 app
(:mod:`mira.app`) can mount.

The per-chunk output-guard hook runs *before* each frame leaves: serialization
is layered on top of :func:`mira.core.streaming.stream`, which invokes the guard
ahead of yielding each event. A raising guard therefore aborts the stream before
the offending chunk is ever formatted or emitted — no chunk bypasses
guardrail-out.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Iterator
from typing import Any

from mira.core.streaming import OutputGuard, StreamEvent, stream

CONTENT_TYPE = "text/event-stream"

# Reuse the WSGI typing surface the warm service already defines (ADR-006) so a
# handler mounted here matches the shape ``mira.app`` expects from health probes.
StartResponse = Any
WSGIHandler = Any


def format_event(event: StreamEvent) -> str:
    """Format one :class:`StreamEvent` as a single SSE frame.

    The event ``kind`` becomes the SSE ``event:`` name; the remaining dataclass
    fields become a JSON object on the ``data:`` line. The frame is terminated
    by the blank line the SSE spec requires between events.
    """
    fields = dataclasses.asdict(event)
    fields.pop("kind", None)
    payload = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return f"event: {event.kind}\ndata: {payload}\n\n"


def sse_frames(
    events: Iterable[StreamEvent],
    guard: OutputGuard | None = None,
) -> Iterator[str]:
    """Yield SSE frame strings for ``events``, running ``guard`` before each emit.

    Wraps :func:`mira.core.streaming.stream` so the guard contract is preserved:
    the guard runs before a frame is formatted, and a raising guard aborts the
    stream mid-flight without emitting the current (or any later) frame. Event
    ordering is preserved; ``done``/``error`` events flow through and terminate
    the stream when they are the last events the producer yields.
    """
    for event in stream(events, guard=guard):
        yield format_event(event)


def sse_response(
    events: Iterable[StreamEvent],
    guard: OutputGuard | None = None,
) -> Iterator[bytes]:
    """Yield UTF-8 encoded SSE frames suitable for a streaming WSGI body."""
    for frame in sse_frames(events, guard=guard):
        yield frame.encode("utf-8")


def make_sse_handler(
    events: Iterable[StreamEvent],
    guard: OutputGuard | None = None,
) -> WSGIHandler:
    """Build a WSGI handler that streams ``events`` as ``text/event-stream``.

    The returned callable matches the WSGI signature used elsewhere in the
    service (``environ``, ``start_response``) and returns a streaming iterable of
    frame bytes — the body is *not* buffered, so frames reach the client as the
    producer yields them. The e03-f07 app mounts this to satisfy the feature AC
    "a streaming endpoint emits typed events".
    """

    def handler(_environ: dict[str, Any], start_response: StartResponse) -> Iterator[bytes]:
        headers = [
            ("Content-Type", CONTENT_TYPE),
            ("Cache-Control", "no-cache"),
            ("Connection", "keep-alive"),
        ]
        start_response("200 OK", headers)
        return sse_response(events, guard=guard)

    return handler
