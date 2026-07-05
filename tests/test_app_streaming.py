"""End-to-end app streaming test (e03-f03-t03).

Boots the composed app with the network-free fake bundle from ``test_app``,
mounts the streaming endpoint (``stream_turn`` → e03-f03-t02
``make_sse_handler``), drives it via a WSGI call, and asserts ordered
``text/event-stream`` frames terminating in ``done`` — criterion #2 demonstrated
with no network.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.app import build_app

from tests.test_app import _fake_bundle  # reuse the network-free fake provider bundle


def _build():
    bundle, _llm = _fake_bundle()
    # Explicit profile keeps the test independent of ambient DEPLOYMENT_PROFILE.
    return build_app("kubernetes", bundle=bundle)


def _reasoning_runner(prompt: str, thread_id: str) -> dict[str, Any]:
    # Stands in for the reasoning loop: a result carrying ordered plan_steps.
    return {
        "plan_steps": [
            {"phase": "plan", "detail": f"plan-1:{prompt}"},
            {"phase": "act", "detail": f"act:plan-1:{prompt}"},
        ],
        "response": f"echo:{prompt}",
        "correlation_id": "corr-stream-1",
    }


def _drive(handler: Any) -> tuple[int, list[tuple[str, str]], list[str]]:
    captured: list[tuple[str, list[tuple[str, str]]]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured.append((status, headers))

    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/stream", "wsgi.input": BytesIO(b"")}
    body = b"".join(handler(environ, start_response)).decode("utf-8")
    status, headers = captured[0]
    frames = [f for f in body.split("\n\n") if f.strip()]
    return int(status.split()[0]), headers, frames


def _name(frame: str) -> str:
    return frame.splitlines()[0][len("event: ") :]


def _data(frame: str) -> dict:
    return json.loads(frame.splitlines()[1][len("data: ") :])


def test_stream_turn_emits_ordered_sse_frames_terminating_in_done() -> None:
    handler = _build().stream_turn("hello", thread_id="t1", runner=_reasoning_runner)

    status, headers, frames = _drive(handler)

    assert status == 200
    assert ("Content-Type", "text/event-stream") in headers
    assert [_name(f) for f in frames] == ["plan_step", "plan_step", "token", "done"]
    assert _data(frames[0]) == {"step": "plan-1:hello", "phase": "plan"}
    assert _data(frames[1]) == {"step": "act:plan-1:hello", "phase": "act"}
    assert _data(frames[2]) == {"text": "echo:hello"}
    assert _data(frames[3]) == {"correlation_id": "corr-stream-1"}


def test_stream_turn_through_real_runtime_terminates_in_done() -> None:
    # Default runner = runtime invoke; the minimal graph records no plan_steps, so
    # the stream is response token → done — still a clean network-free e2e stream.
    status, _, frames = _drive(_build().stream_turn("hello agent", thread_id="t2"))

    names = [_name(f) for f in frames]
    assert status == 200 and names[-1] == "done" and "token" in names
    assert _data(frames[names.index("token")]) == {"text": "echo:hello agent"}


def test_stream_turn_maps_a_failed_run_to_terminal_error() -> None:
    def failing_runner(prompt: str, thread_id: str) -> dict[str, Any]:
        raise RuntimeError("provider exploded")

    status, _, frames = _drive(_build().stream_turn("hello", runner=failing_runner))

    assert status == 200 and [_name(f) for f in frames] == ["error"]
    assert _data(frames[0]) == {"code": "run_failed", "message": "provider exploded"}
