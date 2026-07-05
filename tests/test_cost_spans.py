"""Unit tests for the OTel cost/latency span observer (ADR-042)."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from mira.model.cost_spans import (
    ATTR_COST,
    ATTR_LATENCY_MS,
    ATTR_MODEL,
    ATTR_PROVIDER,
    SPAN_NAME,
    OtelSpanObserver,
)
from mira.model.routing import CostLatencySpan, ModelRoute, Router


class _FakeSpan:
    """Records attributes set on it."""

    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class _FakeTracer:
    """Fake OTel tracer capturing span names and the spans it yields."""

    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []
        self.names: list[str] = []
        self.entered = 0
        self.exited = 0

    @contextmanager
    def start_as_current_span(self, name: str):
        span = _FakeSpan()
        self.spans.append(span)
        self.names.append(name)
        self.entered += 1
        try:
            yield span
        finally:
            self.exited += 1


def test_emit_sets_provider_model_cost_latency_attributes():
    tracer = _FakeTracer()
    observer = OtelSpanObserver(tracer)

    observer.emit(
        CostLatencySpan(provider="openai", model="gpt-4o", cost=4.0, latency_ms=120.0)
    )

    assert tracer.names == [SPAN_NAME]
    assert len(tracer.spans) == 1
    attrs = tracer.spans[0].attributes
    assert attrs[ATTR_PROVIDER] == "openai"
    assert attrs[ATTR_MODEL] == "gpt-4o"
    assert attrs[ATTR_COST] == pytest.approx(4.0)
    assert attrs[ATTR_LATENCY_MS] == pytest.approx(120.0)


def test_emit_opens_and_closes_a_span_per_call():
    tracer = _FakeTracer()
    observer = OtelSpanObserver(tracer)

    observer.emit(CostLatencySpan("p1", "m1", cost=1.0, latency_ms=10.0))
    observer.emit(CostLatencySpan("p2", "m2", cost=2.0, latency_ms=20.0))

    assert tracer.entered == 2
    assert tracer.exited == 2
    assert [s.attributes[ATTR_PROVIDER] for s in tracer.spans] == ["p1", "p2"]


def test_record_call_through_router_emits_otel_span():
    tracer = _FakeTracer()
    route = ModelRoute("anthropic", "claude-haiku", cost_per_1k_tokens=2.0)
    router = Router(routes=[route], span_observer=OtelSpanObserver(tracer))

    span = router.record_call(route, latency_ms=300.0, token_count=2000.0)

    # The router computed the cost; the observer mapped it onto a span.
    assert span.cost == pytest.approx(4.0)
    assert len(tracer.spans) == 1
    attrs = tracer.spans[0].attributes
    assert attrs[ATTR_PROVIDER] == "anthropic"
    assert attrs[ATTR_MODEL] == "claude-haiku"
    assert attrs[ATTR_COST] == pytest.approx(4.0)
    assert attrs[ATTR_LATENCY_MS] == pytest.approx(300.0)


def test_record_call_without_observer_does_not_error():
    route = ModelRoute("google", "gemini-flash", cost_per_1k_tokens=0.5)
    router = Router(routes=[route])  # no span_observer

    span = router.record_call(route, latency_ms=50.0, token_count=1000.0)

    assert span.provider == "google"
    assert span.cost == pytest.approx(0.5)
