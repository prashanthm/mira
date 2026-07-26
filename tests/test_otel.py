"""OTel tracing is opt-in + fail-open: a pure no-op unless an OTLP endpoint is
set and the SDK is installed, and never raises. (The SDK isn't installed in the
test env, so this exercises the disabled path — the critical regression guard.)"""
from __future__ import annotations

import mira.model.otel as otel


def _reset():
    otel._TRACER = None
    otel._TRIED = False


def test_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTLP_ENDPOINT", raising=False)
    _reset()
    assert otel.enabled() is False
    assert otel.tracer() is None
    assert otel.extract_context({"traceparent": "x"}) is None
    with otel.span("t", attributes={"a": 1}) as s:
        assert s is None                       # no-op yields None, no raise
    otel.gen_ai_span(op="classify", agent="synthesis", model="m", provider="p",
                     request="q", response="a", usage={"prompt_tokens": 1},
                     cost_usd=0.001, latency_ms=10.0, correlation_id="c", error=None)


def test_endpoint_set_but_sdk_absent_stays_noop(monkeypatch):
    """Endpoint configured but the otel SDK not installed → still a no-op."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    _reset()
    # SDK isn't installed in the test env → tracer init fails → disabled
    assert otel.enabled() is False
    with otel.span("t") as s:
        assert s is None


def test_inbound_trace_headers_default_empty():
    from mira.core.service import inbound_trace_headers
    assert inbound_trace_headers() == {}
