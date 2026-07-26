"""CORS middleware for the agent-facing WSGI surface (ADR-006 Phase V1).

Browser clients (the chat UI dev server) call the agent API cross-origin. This
small, framework-free WSGI wrapper adds the CORS response headers and answers
``OPTIONS`` preflight for the service's known routes.

Policy:

* ``CORS_ALLOW_ORIGINS`` env — comma-separated exact origins. When unset, the
  default allows any local dev origin: ``http://localhost[:PORT]`` and
  ``http://127.0.0.1[:PORT]``.
* An allowed request ``Origin`` is echoed back in
  ``Access-Control-Allow-Origin`` (never ``*`` — the echo keeps the policy
  origin-exact and cache-safe via ``Vary: Origin``).
* A disallowed origin gets **no** CORS headers; the request is still served —
  the browser enforces the block, the server never rejects on origin alone.
* ``OPTIONS`` preflight on a known path is answered ``204 No Content`` without
  reaching the wrapped app.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from typing import Any

CORS_ALLOW_ORIGINS_ENV = "CORS_ALLOW_ORIGINS"

ALLOW_METHODS = "GET,POST,OPTIONS"
ALLOW_HEADERS = "Content-Type, traceparent, tracestate"

# Default policy: any localhost / loopback dev origin, any port (or none).
_LOCAL_ORIGIN_RE = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")

StartResponse = Callable[..., Any]
WSGIApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]


def allowed_origins_from_env(environ: dict[str, str] | None = None) -> tuple[str, ...] | None:
    """Parse ``CORS_ALLOW_ORIGINS``; ``None`` means "use the localhost default"."""
    env = environ if environ is not None else os.environ
    raw = (env.get(CORS_ALLOW_ORIGINS_ENV) or "").strip()
    if not raw:
        return None
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


def origin_allowed(origin: str, allow_list: tuple[str, ...] | None) -> bool:
    """Whether ``origin`` may receive CORS headers under the resolved policy."""
    if not origin:
        return False
    if allow_list is None:
        return bool(_LOCAL_ORIGIN_RE.match(origin))
    return origin in allow_list


def _cors_headers(origin: str) -> list[tuple[str, str]]:
    return [
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Methods", ALLOW_METHODS),
        ("Access-Control-Allow-Headers", ALLOW_HEADERS),
        ("Vary", "Origin"),
    ]


def wrap_cors(app: WSGIApp, *, preflight_paths: frozenset[str]) -> WSGIApp:
    """Wrap ``app`` with the CORS policy; answer preflight for ``preflight_paths``.

    The env policy is re-read per request so a config change (or a test
    ``monkeypatch.setenv``) takes effect without rebuilding the service.
    """

    def middleware(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        origin = environ.get("HTTP_ORIGIN", "")
        allowed = origin_allowed(origin, allowed_origins_from_env())
        extra = _cors_headers(origin) if allowed else []

        if (
            environ.get("REQUEST_METHOD", "GET").upper() == "OPTIONS"
            and environ.get("PATH_INFO", "") in preflight_paths
        ):
            start_response("204 No Content", [*extra, ("Content-Length", "0")])
            return [b""]

        def cors_start_response(status: str, headers: list[tuple[str, str]], *args: Any) -> Any:
            return start_response(status, list(headers) + extra, *args)

        return app(environ, cors_start_response)

    return middleware


__all__ = [
    "ALLOW_HEADERS",
    "ALLOW_METHODS",
    "CORS_ALLOW_ORIGINS_ENV",
    "allowed_origins_from_env",
    "origin_allowed",
    "wrap_cors",
]
