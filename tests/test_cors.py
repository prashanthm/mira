"""Tests for the CORS middleware on the WSGI surface (ADR-006 Phase V1)."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.core.cors import CORS_ALLOW_ORIGINS_ENV
from mira.core.service import LIVE_PATH, TURN_PATH, create_app


def _call(
    app: Any,
    path: str,
    *,
    method: str = "GET",
    origin: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    captured: list[tuple[str, list[tuple[str, str]]]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured.append((status, headers))

    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "wsgi.input": BytesIO(b""),
    }
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    body = b"".join(app(environ, start_response))
    status, headers = captured[0]
    return int(status.split()[0]), dict(headers), body


def _service() -> Any:
    return create_app(deps_ready=lambda: True).wsgi_app


def test_allowed_localhost_origin_is_echoed_by_default() -> None:
    status, headers, body = _call(_service(), LIVE_PATH, origin="http://localhost:3000")
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert headers["Access-Control-Allow-Methods"] == "GET,POST,OPTIONS"
    assert "traceparent" in headers["Access-Control-Allow-Headers"]  # W3C trace propagation
    assert "Content-Type" in headers["Access-Control-Allow-Headers"]
    assert json.loads(body) == {"status": "ok"}


def test_loopback_ip_origin_allowed_by_default() -> None:
    _, headers, _ = _call(_service(), LIVE_PATH, origin="http://127.0.0.1:5173")
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"


def test_disallowed_origin_gets_no_cors_headers_but_is_served() -> None:
    status, headers, body = _call(_service(), LIVE_PATH, origin="http://evil.example")
    assert status == 200  # server still answers; the browser enforces the block
    assert "Access-Control-Allow-Origin" not in headers
    assert json.loads(body) == {"status": "ok"}


def test_request_without_origin_gets_no_cors_headers() -> None:
    status, headers, _ = _call(_service(), LIVE_PATH)
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers


def test_options_preflight_on_known_path_returns_204() -> None:
    status, headers, body = _call(
        _service(), TURN_PATH, method="OPTIONS", origin="http://localhost:3000"
    )
    assert status == 204
    assert body == b""
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert "traceparent" in headers["Access-Control-Allow-Headers"]


def test_options_preflight_on_unknown_path_falls_through() -> None:
    status, _, body = _call(
        _service(), "/nope", method="OPTIONS", origin="http://localhost:3000"
    )
    assert status == 404
    assert json.loads(body) == {"error": "not_found"}


def test_env_override_replaces_default_policy(monkeypatch) -> None:
    monkeypatch.setenv(
        CORS_ALLOW_ORIGINS_ENV, "https://app.example.com, https://ops.example.com"
    )
    app = _service()

    _, headers, _ = _call(app, LIVE_PATH, origin="https://app.example.com")
    assert headers["Access-Control-Allow-Origin"] == "https://app.example.com"

    _, headers, _ = _call(app, LIVE_PATH, origin="https://ops.example.com")
    assert headers["Access-Control-Allow-Origin"] == "https://ops.example.com"

    # The localhost default no longer applies once an explicit list is set.
    _, headers, _ = _call(app, LIVE_PATH, origin="http://localhost:3000")
    assert "Access-Control-Allow-Origin" not in headers
