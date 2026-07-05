"""Tests for warm service lifecycle (ADR-008/006)."""

from __future__ import annotations

import json
import signal
import threading
import time
from io import BytesIO
from typing import Any

import pytest

from mira.core.service import (
    LIVE_PATH,
    READY_PATH,
    STARTUP_PATH,
    ServiceDrainingError,
    WarmService,
    create_app,
)


@pytest.fixture
def _restore_sigterm():
    original = signal.getsignal(signal.SIGTERM)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, original)


def _call_wsgi(app, path: str, method: str = "GET") -> tuple[int, dict[str, str], dict[str, Any]]:
    status_holder: list[str] = []
    headers_holder: list[tuple[str, str]] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder.append(status)
        headers_holder.extend(headers)

    environ = {
        "REQUEST_METHOD": method,
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
    status_code = int(status_holder[0].split()[0])
    payload = json.loads(body.decode("utf-8"))
    return status_code, dict(headers_holder), payload


def test_liveness_always_ok():
    service = create_app(deps_ready=lambda: False)
    status, _, payload = _call_wsgi(service.wsgi_app, LIVE_PATH)
    assert status == 200
    assert payload == {"status": "ok"}
    assert service.is_live()


def test_readiness_not_ready_until_deps_and_startup():
    deps_up = False
    service = create_app(deps_ready=lambda: deps_up)

    status, _, payload = _call_wsgi(service.wsgi_app, READY_PATH)
    assert status == 503
    assert payload == {"status": "not_ready"}

    service.mark_startup_complete()
    status, _, payload = _call_wsgi(service.wsgi_app, READY_PATH)
    assert status == 503
    assert payload == {"status": "not_ready"}

    deps_up = True
    status, _, payload = _call_wsgi(service.wsgi_app, READY_PATH)
    assert status == 200
    assert payload == {"status": "ready"}


def test_startup_probe_gates_until_warmup_complete():
    deps_up = False
    service = create_app(deps_ready=lambda: deps_up)

    status, _, payload = _call_wsgi(service.wsgi_app, STARTUP_PATH)
    assert status == 503
    assert payload == {"status": "starting"}

    service.mark_startup_complete()
    deps_up = True
    status, _, payload = _call_wsgi(service.wsgi_app, STARTUP_PATH)
    assert status == 200
    assert payload == {"status": "started"}


def test_sigterm_drain_waits_for_in_flight_work():
    service = WarmService(deps_ready=lambda: True, drain_timeout=2.0)
    service.mark_startup_complete()

    entered = threading.Event()
    release = threading.Event()
    work_finished = threading.Event()

    def worker() -> None:
        with service.track_in_flight():
            entered.set()
            release.wait(timeout=2.0)
            work_finished.set()

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=1.0)

    shutdown = threading.Thread(target=service.begin_shutdown)
    shutdown.start()
    time.sleep(0.05)

    assert service.draining
    status, _, payload = _call_wsgi(service.wsgi_app, READY_PATH)
    assert status == 503
    assert payload == {"status": "not_ready"}
    assert not work_finished.is_set()

    release.set()
    shutdown.join(timeout=2.0)
    thread.join(timeout=2.0)
    assert work_finished.is_set()


def test_nested_track_in_flight_counts_each_scope():
    # H1: nested scopes on one thread must each count; inner exit must not empty
    # the in-flight set while the outer scope is still active.
    service = WarmService(deps_ready=lambda: True, drain_timeout=2.0)
    drained_early = threading.Event()

    with service.track_in_flight():
        with service.track_in_flight():
            pass  # inner scope exits
        # outer still active: a drain started now must NOT complete immediately
        shutdown = threading.Thread(target=service.begin_shutdown)
        shutdown.start()
        time.sleep(0.05)
        if service._drain_complete.is_set():
            drained_early.set()
    shutdown.join(timeout=2.0)

    assert not drained_early.is_set()
    assert service._drain_complete.is_set()  # completes once outer scope exits


def test_track_in_flight_rejects_new_work_while_draining():
    # M2: starting new work after drain begins must raise.
    service = WarmService(deps_ready=lambda: True, drain_timeout=0.2)
    service.begin_shutdown()  # no in-flight -> drains immediately, _draining=True

    assert service.draining
    with pytest.raises(ServiceDrainingError):
        with service.track_in_flight():
            pass


def test_sigterm_handler_exits_after_drain(_restore_sigterm):
    # H2: the handler runs drain off the signal thread and then calls the exit
    # callback; we inject a callback instead of os._exit so the test survives.
    service = WarmService(deps_ready=lambda: True, drain_timeout=2.0)
    exited = threading.Event()
    service.register_sigterm_handler(on_drained=exited.set)

    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler)
    handler(signal.SIGTERM, None)  # invoke as if SIGTERM was delivered

    assert exited.wait(timeout=2.0)  # drain completed and exit callback fired


def test_register_sigterm_handler_is_idempotent(_restore_sigterm):
    service = create_app(deps_ready=lambda: True)
    service.register_sigterm_handler(on_drained=lambda: None)
    first = signal.getsignal(signal.SIGTERM)
    service.register_sigterm_handler(on_drained=lambda: None)
    second = signal.getsignal(signal.SIGTERM)

    assert callable(first) and callable(second)
    assert first is not signal.SIG_DFL and second is not signal.SIG_DFL
