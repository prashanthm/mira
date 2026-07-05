"""Tests for /health SLO surfacing (ADR-043 on the ADR-008 warm service)."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.config.slos import Slo, SloTracker
from mira.core.service import LIVE_PATH, READY_PATH, create_app


def _call_wsgi(app, path: str) -> tuple[int, dict[str, Any]]:
    status_holder: list[str] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder.append(status)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "wsgi.input": BytesIO(b""),
        "wsgi.errors": None,
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
    }
    body = b"".join(app(environ, start_response))
    return int(status_holder[0].split()[0]), json.loads(body.decode("utf-8"))


def _tracker() -> SloTracker:
    return SloTracker([Slo("turns", "turn success", objective=0.9, window_events=4)])


def test_health_without_tracker_is_unchanged() -> None:
    service = create_app(deps_ready=lambda: True)
    status, payload = _call_wsgi(service.wsgi_app, LIVE_PATH)
    assert status == 200
    assert payload == {"status": "ok"}  # byte-identical no-tracker behavior


def test_health_with_tracker_includes_slos_payload() -> None:
    tracker = _tracker()
    tracker.record("turns", True)
    tracker.record("turns", False)
    service = create_app(deps_ready=lambda: True, slo_tracker=tracker)

    status, payload = _call_wsgi(service.wsgi_app, LIVE_PATH)

    assert status == 200
    assert payload["status"] == "ok"
    entry = payload["slos"]["turns"]
    assert entry["objective"] == 0.9
    assert entry["good"] == 1
    assert entry["total"] == 2
    assert entry["healthy"] is False


def test_liveness_stays_ok_while_slo_budget_burns() -> None:
    # Liveness must not flap on SLO burn: burn pages (ADR-044), never restarts.
    tracker = _tracker()
    for _ in range(4):
        tracker.record("turns", False)
    service = create_app(deps_ready=lambda: True, slo_tracker=tracker)

    status, payload = _call_wsgi(service.wsgi_app, LIVE_PATH)

    assert status == 200
    assert payload["status"] == "ok"
    assert payload["slos"]["turns"]["error_budget_remaining_ratio"] == 0.0
    assert payload["slos"]["turns"]["healthy"] is False


def test_readiness_path_is_unaffected_by_tracker() -> None:
    tracker = _tracker()
    tracker.record("turns", False)  # unhealthy SLO

    ready_service = create_app(deps_ready=lambda: True, slo_tracker=tracker)
    ready_service.mark_startup_complete()
    status, payload = _call_wsgi(ready_service.wsgi_app, READY_PATH)
    assert status == 200
    assert payload == {"status": "ready"}  # same body as the no-tracker service

    not_ready = create_app(deps_ready=lambda: False, slo_tracker=tracker)
    status, payload = _call_wsgi(not_ready.wsgi_app, READY_PATH)
    assert status == 503
    assert payload == {"status": "not_ready"}
