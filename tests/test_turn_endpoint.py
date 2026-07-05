"""Tests for the POST /turn SSE endpoint (ADR-006 Phase V1).

Drives the warm service WSGI surface directly: request validation (400/405/503),
delegation to the app-supplied SSE turn handler, supervisor-first routing when
an agent-card registry is wired, and the runtime fallback for unmatched prompts.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

from mira.app import App, build_app
from mira.core.service import TURN_PATH, create_app
from mira.core.streaming import Done
from mira.core.streaming_sse import make_sse_handler
from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.specialists.research import REPRESENTATIVE_RESEARCH_QUERY

from tests.test_app import _fake_bundle  # reuse the network-free fake provider bundle

FIXTURES = Path(__file__).parent / "fixtures"


def _post_turn(
    app: Any,
    body: bytes | dict[str, Any],
    method: str = "POST",
) -> tuple[int, dict[str, str], str]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    captured: list[tuple[str, list[tuple[str, str]]]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured.append((status, headers))

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": TURN_PATH,
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": BytesIO(raw),
    }
    payload = b"".join(app(environ, start_response)).decode("utf-8")
    status, headers = captured[0]
    return int(status.split()[0]), dict(headers), payload


def _frames(body: str) -> list[str]:
    return [f for f in body.split("\n\n") if f.strip()]


def _name(frame: str) -> str:
    return frame.splitlines()[0][len("event: ") :]


def _data(frame: str) -> dict[str, Any]:
    return json.loads(frame.splitlines()[1][len("data: ") :])


def _build(registry: Any | None = None) -> App:
    bundle, _llm = _fake_bundle()
    # Explicit profile keeps the test independent of ambient DEPLOYMENT_PROFILE.
    return build_app("kubernetes", bundle=bundle, registry=registry)


def _demo_registry() -> Any:
    return build_demo_registry(str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv"))


def test_post_turn_streams_sse_frames_terminating_in_done() -> None:
    app = _build()
    status, headers, body = _post_turn(app.wsgi_app, {"prompt": "hello turn"})

    assert status == 200
    assert headers["Content-Type"] == "text/event-stream"
    frames = _frames(body)
    names = [_name(f) for f in frames]
    assert names[-1] == "done" and "token" in names
    assert _data(frames[names.index("token")]) == {"text": "echo:hello turn"}


def test_post_turn_missing_prompt_returns_400() -> None:
    app = _build()
    status, _, body = _post_turn(app.wsgi_app, {"thread_id": "t"})
    assert status == 400
    assert json.loads(body)["error"] == "invalid_request"


def test_post_turn_non_string_prompt_returns_400() -> None:
    app = _build()
    status, _, body = _post_turn(app.wsgi_app, {"prompt": 42})
    assert status == 400
    assert json.loads(body)["error"] == "invalid_request"


def test_post_turn_malformed_json_returns_400() -> None:
    app = _build()
    status, _, body = _post_turn(app.wsgi_app, b"{not json")
    assert status == 400
    assert json.loads(body)["error"] == "invalid_request"


def test_post_turn_empty_body_returns_400() -> None:
    app = _build()
    status, _, body = _post_turn(app.wsgi_app, b"")
    assert status == 400
    assert json.loads(body)["error"] == "invalid_request"


def test_get_turn_returns_405() -> None:
    app = _build()
    status, _, body = _post_turn(app.wsgi_app, {"prompt": "hi"}, method="GET")
    assert status == 405
    assert json.loads(body) == {"error": "method_not_allowed"}


def test_turn_unconfigured_returns_503() -> None:
    service = create_app(deps_ready=lambda: True)  # no turn_handler wired
    status, _, body = _post_turn(service.wsgi_app, {"prompt": "hi"})
    assert status == 503
    assert json.loads(body) == {"error": "turns_unavailable"}


def test_turn_thread_id_defaults_to_web_and_is_forwarded() -> None:
    seen: list[tuple[str, str]] = []

    def factory(prompt: str, thread_id: str) -> Any:
        seen.append((prompt, thread_id))
        return make_sse_handler([Done()])

    service = create_app(deps_ready=lambda: True, turn_handler=factory)

    status, _, _ = _post_turn(service.wsgi_app, {"prompt": "one"})
    assert status == 200
    status, _, _ = _post_turn(service.wsgi_app, {"prompt": "two", "thread_id": "custom"})
    assert status == 200
    assert seen == [("one", "web"), ("two", "custom")]


def test_supervisor_routed_turn_streams_plan_steps_and_synthesis() -> None:
    app = _build(registry=_demo_registry())
    status, headers, body = _post_turn(
        app.wsgi_app, {"prompt": REPRESENTATIVE_RESEARCH_QUERY}
    )

    assert status == 200
    assert headers["Content-Type"] == "text/event-stream"
    frames = _frames(body)
    names = [_name(f) for f in frames]

    # The specialist's recorded plan steps stream ahead of the synthesis token.
    assert names.count("plan_step") >= 1
    assert names.index("plan_step") < names.index("token")
    token = _data(frames[names.index("token")])
    assert token["text"].startswith("[research]")
    assert "middleware" in token["text"]

    done = _data(frames[-1])
    assert names[-1] == "done"
    assert isinstance(done["correlation_id"], str) and done["correlation_id"]


def test_unmatched_prompt_falls_back_to_runtime_stream() -> None:
    app = _build(registry=_demo_registry())
    status, _, body = _post_turn(
        app.wsgi_app, {"prompt": "completely unrelated question"}
    )

    assert status == 200
    frames = _frames(body)
    names = [_name(f) for f in frames]
    assert names[-1] == "done" and "token" in names
    # Fallback is the default runtime turn (echo model path), not the supervisor.
    assert _data(frames[names.index("token")]) == {
        "text": "echo:completely unrelated question"
    }
