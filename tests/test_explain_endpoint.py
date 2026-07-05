"""Tests for the /explain endpoint over the decision-trace store (ADR-041)."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.core.decision_trace import TraceStore
from mira.core.service import EXPLAIN_PATH, WarmService, create_app


def _call_wsgi(
    app, path: str, query_string: str = ""
) -> tuple[int, dict[str, Any]]:
    status_holder: list[str] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder.append(status)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
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
    return status_code, json.loads(body.decode("utf-8"))


def _populated_store() -> TraceStore:
    ticks = iter(range(1, 100))
    store = TraceStore(clock=lambda: float(next(ticks)))
    store.record_from_result(
        "trace-1",
        "corr-1",
        {
            "domain": "research",
            "query": "middleware ordering?",
            "answer": {
                "snippet": "fixed stage order",
                "provenance": {"source_type": "docs", "source_id": "handbook.md"},
            },
            "plan_steps": [{"event": "plan_step", "phase": "plan", "detail": "p", "index": 0}],
        },
    )
    store.record_from_result(
        "trace-2",
        "corr-1",
        {"query": "unsourced claim?", "answer": {"snippet": "no provenance"}, "plan_steps": []},
        guardrail_findings=[{"code": "ungrounded_answer"}],
    )
    return store


def _service() -> WarmService:
    return create_app(deps_ready=lambda: True, trace_store=_populated_store())


def test_explain_by_trace_id_hit() -> None:
    service = _service()
    status, payload = _call_wsgi(service.wsgi_app, EXPLAIN_PATH, "trace_id=trace-1")

    assert status == 200
    assert payload["trace_id"] == "trace-1"
    assert payload["correlation_id"] == "corr-1"
    assert payload["claims"][0]["source_id"] == "handbook.md"
    assert payload["plan_steps"][0]["phase"] == "plan"
    assert payload["uncertainty"]["band"] == "supported"
    assert payload["uncertainty"]["grounded_ratio"] == 1.0


def test_explain_miss_returns_404() -> None:
    service = _service()
    status, payload = _call_wsgi(service.wsgi_app, EXPLAIN_PATH, "trace_id=nope")
    assert status == 404
    assert payload == {"error": "trace_not_found"}


def test_explain_by_correlation_id_lists_records() -> None:
    service = _service()
    status, payload = _call_wsgi(service.wsgi_app, EXPLAIN_PATH, "correlation_id=corr-1")

    assert status == 200
    records = payload["records"]
    assert [r["trace_id"] for r in records] == ["trace-1", "trace-2"]
    # Findings and uncertainty surface per record.
    assert records[1]["guardrail_findings"] == [{"code": "ungrounded_answer"}]
    assert records[1]["uncertainty"]["band"] == "unsupported"
    assert records[1]["uncertainty"]["has_guardrail_findings"] is True


def test_explain_missing_params_returns_400() -> None:
    service = _service()
    status, payload = _call_wsgi(service.wsgi_app, EXPLAIN_PATH)
    assert status == 400
    assert payload["error"] == "missing_parameter"


def test_explain_unconfigured_store_returns_503() -> None:
    service = create_app(deps_ready=lambda: True)  # no trace_store
    status, payload = _call_wsgi(service.wsgi_app, EXPLAIN_PATH, "trace_id=trace-1")
    assert status == 503
    assert payload == {"error": "explanations_unavailable"}


def test_health_routes_unaffected_by_trace_store() -> None:
    service = _service()
    status, payload = _call_wsgi(service.wsgi_app, "/health")
    assert status == 200
    assert payload == {"status": "ok"}
