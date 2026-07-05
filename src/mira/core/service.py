"""Warm service lifecycle — health probes and graceful SIGTERM drain (ADR-008/006).

Health probe paths: ``/health`` (liveness) and ``/health/ready`` (readiness) per
ADR-006, plus ``/health/startup`` — a Kubernetes startup probe for slow warmup
(provider init / MCP warmup). The startup path is a Mira extension of the
ADR-006 probe table; ops manifests should configure it as the K8s startupProbe.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

StartResponse = Callable[[str, list[tuple[str, str]]], Any]
WSGIApp = Callable[[dict[str, Any], StartResponse], list[bytes]]

LIVE_PATH = "/health"
READY_PATH = "/health/ready"
STARTUP_PATH = "/health/startup"


class ServiceDrainingError(RuntimeError):
    """Raised when new in-flight work is started after drain has begun."""


class WarmService:
    """Long-running warm service with liveness/readiness probes and graceful drain."""

    def __init__(
        self,
        *,
        deps_ready: Callable[[], bool] | None = None,
        drain_timeout: float = 30.0,
    ) -> None:
        self._deps_ready = deps_ready or (lambda: False)
        self._drain_timeout = drain_timeout
        self._draining = False
        self._startup_complete = False
        # Per-scope tokens (object identity), not thread id: nested track_in_flight
        # on one thread must count as two distinct units so the inner scope exiting
        # doesn't prematurely empty _in_flight (H1).
        self._in_flight: set[object] = set()
        self._in_flight_lock = threading.Lock()
        self._drain_complete = threading.Event()

    def mark_startup_complete(self) -> None:
        """Signal that slow startup (provider init, MCP warmup) has finished."""
        self._startup_complete = True

    @property
    def draining(self) -> bool:
        return self._draining

    @contextmanager
    def track_in_flight(self) -> Iterator[None]:
        """Track a unit of in-flight work for SIGTERM drain.

        Raises :class:`ServiceDrainingError` if entered after drain has begun, so
        new work cannot extend the drain window indefinitely (M2).
        """
        token = object()
        with self._in_flight_lock:
            if self._draining:
                raise ServiceDrainingError("service is draining; not accepting new work")
            self._in_flight.add(token)
        try:
            yield
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(token)
                if self._draining and not self._in_flight:
                    self._drain_complete.set()

    def register_sigterm_handler(self, *, on_drained: Callable[[], None] | None = None) -> None:
        """Register a SIGTERM handler that drains in-flight work on a background
        thread, then invokes ``on_drained`` (defaults to ``os._exit(0)``).

        The handler itself only sets a flag and spawns the drain thread — it does
        not block in signal context (unsafe in CPython), so it cannot deadlock on
        locks held by the main thread (H2).
        """
        exit_fn = on_drained or (lambda: os._exit(0))

        def _handler(*_args: Any) -> None:
            t = threading.Thread(
                target=lambda: (self.begin_shutdown(), exit_fn()),
                name="mira-sigterm-drain",
                daemon=True,
            )
            t.start()

        signal.signal(signal.SIGTERM, _handler)

    def begin_shutdown(self) -> None:
        """Stop accepting new work, drain in-flight requests, then return when the
        in-flight set empties or the drain timeout elapses."""
        self._draining = True
        with self._in_flight_lock:
            if not self._in_flight:
                self._drain_complete.set()
        self._drain_complete.wait(timeout=self._drain_timeout)

    def is_live(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return (
            not self._draining
            and self._startup_complete
            and self._deps_ready()
        )

    def is_startup_complete(self) -> bool:
        return self._startup_complete and self._deps_ready()

    @property
    def wsgi_app(self) -> WSGIApp:
        return self._handle_request

    def _handle_request(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> list[bytes]:
        path = environ.get("PATH_INFO", "")
        if path == LIVE_PATH:
            return self._json_response(start_response, 200, {"status": "ok"})
        if path == READY_PATH:
            if self.is_ready():
                return self._json_response(start_response, 200, {"status": "ready"})
            return self._json_response(start_response, 503, {"status": "not_ready"})
        if path == STARTUP_PATH:
            if self.is_startup_complete():
                return self._json_response(start_response, 200, {"status": "started"})
            return self._json_response(start_response, 503, {"status": "starting"})
        return self._json_response(start_response, 404, {"error": "not_found"})

    @staticmethod
    def _json_response(
        start_response: StartResponse,
        status_code: int,
        payload: dict[str, str],
    ) -> list[bytes]:
        body = json.dumps(payload).encode("utf-8")
        reason = http.client.responses.get(status_code, "Unknown")
        status = f"{status_code} {reason}"
        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ]
        start_response(status, headers)
        return [body]


def create_app(*, deps_ready: Callable[[], bool] | None = None) -> WarmService:
    """Build a warm service instance with health probe routes."""
    return WarmService(deps_ready=deps_ready)
