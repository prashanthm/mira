"""Tests for the cost-attribution ledger and anomaly detection (ADR-042)."""

from __future__ import annotations

import pytest

from mira.model.cost_attribution import (
    AnomalyDetector,
    AttributedSpan,
    CostLedger,
    CostTotal,
    LedgerSpanObserver,
)
from mira.model.gateway import Gateway
from mira.model.routing import CostLatencySpan, ModelRoute, Router


def _span(
    *,
    provider: str = "anthropic",
    model: str = "claude-haiku",
    cost: float = 1.0,
    latency_ms: float = 100.0,
    tenant: str = "",
    domain: str = "",
    tool: str = "",
    correlation_id: str = "",
) -> AttributedSpan:
    return AttributedSpan(
        provider=provider,
        model=model,
        cost=cost,
        latency_ms=latency_ms,
        tenant=tenant,
        domain=domain,
        tool=tool,
        correlation_id=correlation_id,
    )


# --- AttributedSpan ---

def test_from_span_carries_span_fields_and_dims() -> None:
    span = CostLatencySpan(provider="openai", model="gpt-4o", cost=4.0, latency_ms=120.0)
    attributed = AttributedSpan.from_span(
        span, tenant="t1", domain="finance", tool="ledger.query", correlation_id="c-1"
    )
    assert attributed.provider == "openai"
    assert attributed.model == "gpt-4o"
    assert attributed.cost == pytest.approx(4.0)
    assert attributed.latency_ms == pytest.approx(120.0)
    assert attributed.tenant == "t1"
    assert attributed.domain == "finance"
    assert attributed.tool == "ledger.query"
    assert attributed.correlation_id == "c-1"


def test_attribution_dims_default_to_empty_strings() -> None:
    attributed = AttributedSpan.from_span(
        CostLatencySpan(provider="p", model="m", cost=0.5, latency_ms=10.0)
    )
    assert (attributed.tenant, attributed.domain, attributed.tool) == ("", "", "")
    assert attributed.correlation_id == ""


# --- CostLedger aggregation ---

def test_ledger_totals_by_tenant() -> None:
    ledger = CostLedger()
    ledger.record(_span(tenant="t1", cost=1.0, latency_ms=100.0))
    ledger.record(_span(tenant="t1", cost=2.0, latency_ms=300.0))
    ledger.record(_span(tenant="t2", cost=5.0, latency_ms=50.0))

    totals = ledger.totals(by="tenant")
    assert totals["t1"] == CostTotal(cost=3.0, calls=2, mean_latency_ms=200.0)
    assert totals["t2"] == CostTotal(cost=5.0, calls=1, mean_latency_ms=50.0)


def test_ledger_totals_across_every_dimension() -> None:
    ledger = CostLedger()
    ledger.record(
        _span(provider="p1", model="m1", tenant="t1", domain="d1", tool="k1", cost=1.0)
    )
    ledger.record(
        _span(provider="p2", model="m2", tenant="t2", domain="d2", tool="k2", cost=2.0)
    )

    for dimension, keys in (
        ("tenant", {"t1", "t2"}),
        ("domain", {"d1", "d2"}),
        ("tool", {"k1", "k2"}),
        ("model", {"m1", "m2"}),
        ("provider", {"p1", "p2"}),
    ):
        totals = ledger.totals(by=dimension)  # type: ignore[arg-type]
        assert set(totals) == keys


def test_ledger_total_cost_and_empty_ledger() -> None:
    ledger = CostLedger()
    assert ledger.total_cost() == 0.0
    assert ledger.totals(by="tenant") == {}
    assert ledger.spans == ()

    ledger.record(_span(cost=1.5))
    ledger.record(_span(cost=2.5))
    assert ledger.total_cost() == pytest.approx(4.0)


# --- LedgerSpanObserver (SpanObserver protocol conformance) ---

def test_observer_records_span_with_resolved_dims() -> None:
    ledger = CostLedger()
    dims = {"tenant": "acme", "domain": "research", "tool": "docs.search", "correlation_id": "c-9"}
    observer = LedgerSpanObserver(ledger, dims=lambda: dims)

    observer.emit(CostLatencySpan(provider="p", model="m", cost=2.0, latency_ms=40.0))

    (recorded,) = ledger.spans
    assert recorded.tenant == "acme"
    assert recorded.domain == "research"
    assert recorded.tool == "docs.search"
    assert recorded.correlation_id == "c-9"
    assert recorded.cost == pytest.approx(2.0)


def test_observer_without_dims_resolver_records_unattributed() -> None:
    ledger = CostLedger()
    observer = LedgerSpanObserver(ledger)
    observer.emit(CostLatencySpan(provider="p", model="m", cost=1.0, latency_ms=10.0))
    (recorded,) = ledger.spans
    assert (recorded.tenant, recorded.domain, recorded.tool) == ("", "", "")


def test_router_record_call_flows_into_ledger_like_otel_observer() -> None:
    # Same attachment seam as OtelSpanObserver in test_cost_spans.py: the
    # router computes the cost and the observer receives the span.
    ledger = CostLedger()
    route = ModelRoute("anthropic", "claude-haiku", cost_per_1k_tokens=2.0)
    router = Router(
        routes=[route],
        span_observer=LedgerSpanObserver(ledger, dims=lambda: {"tenant": "t1"}),
    )

    router.record_call(route, latency_ms=300.0, token_count=2000.0)

    totals = ledger.totals(by="tenant")
    assert totals["t1"] == CostTotal(cost=4.0, calls=1, mean_latency_ms=300.0)


# --- Integration: gateway-emitted span -> ledger totals ---

class _FakeLLMProvider:
    def complete(self, prompt: str, *, model: str | None = None) -> str:
        return f"fake:{prompt}"

    def embed(self, text: str) -> list[float]:
        return [float(len(text))]


class _FakeBundle:
    def __init__(self) -> None:
        self.llm = _FakeLLMProvider()


def test_gateway_call_flows_through_ledger_observer_into_totals() -> None:
    # The real gateway seam (ADR-010): a routed completion emits one span to
    # the configured SpanObserver; the LedgerSpanObserver attributes and
    # records it exactly like OtelSpanObserver maps it onto OTel.
    ledger = CostLedger()
    ticks = iter([0.0, 0.25])  # injected clock: 250ms latency, deterministic
    route = ModelRoute("anthropic", "claude-haiku", cost_per_1k_tokens=2.0)
    gateway = Gateway(
        _FakeBundle(),  # type: ignore[arg-type]
        router=Router(routes=[route]),
        span_observer=LedgerSpanObserver(
            ledger, dims=lambda: {"tenant": "t1", "domain": "finance"}
        ),
        clock=lambda: next(ticks),
    )

    result = gateway.complete("hello", tenant="t1")

    assert result == "fake:hello"
    by_tenant = ledger.totals(by="tenant")
    assert by_tenant["t1"].calls == 1
    assert by_tenant["t1"].cost == pytest.approx(2.0)
    assert by_tenant["t1"].mean_latency_ms == pytest.approx(250.0)
    assert ledger.totals(by="domain")["finance"].calls == 1
    assert ledger.totals(by="provider")["anthropic"].calls == 1


# --- AnomalyDetector ---

def test_no_anomalies_below_all_thresholds() -> None:
    detector = AnomalyDetector(
        span_cost_ceiling=10.0,
        budget_caps={("tenant", "t1"): 100.0},
        spike_factor=3.0,
    )
    window = [_span(tenant="t1", cost=1.0) for _ in range(3)]
    assert detector.check(window, baseline_count=1) == []


def test_thresholds_are_exclusive_at_the_boundary() -> None:
    # Exactly-at-limit is NOT an anomaly for any rule (no false positives).
    detector = AnomalyDetector(
        span_cost_ceiling=5.0,
        budget_caps={("tenant", "t1"): 10.0},
        spike_factor=2.0,
    )
    window = [_span(tenant="t1", cost=5.0), _span(tenant="t1", cost=5.0)]
    assert detector.check(window, baseline_count=1) == []


def test_single_span_cost_ceiling_breach() -> None:
    detector = AnomalyDetector(span_cost_ceiling=5.0)
    window = [_span(cost=1.0), _span(cost=6.0, correlation_id="c-42")]

    anomalies = detector.check(window)

    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly.kind == "cost_ceiling"
    assert anomaly.dimension == "span"
    assert anomaly.observed == pytest.approx(6.0)
    assert anomaly.limit == pytest.approx(5.0)
    assert "c-42" in anomaly.detail


def test_dimension_budget_cap_breach() -> None:
    detector = AnomalyDetector(budget_caps={("tenant", "t1"): 3.0})
    window = [
        _span(tenant="t1", cost=2.0),
        _span(tenant="t1", cost=2.0),
        _span(tenant="t2", cost=100.0),  # uncapped tenant never fires
    ]

    anomalies = detector.check(window)

    assert [a.kind for a in anomalies] == ["budget_cap"]
    assert anomalies[0].dimension == "tenant:t1"
    assert anomalies[0].observed == pytest.approx(4.0)
    assert anomalies[0].limit == pytest.approx(3.0)


def test_call_rate_spike_against_explicit_baseline() -> None:
    detector = AnomalyDetector(spike_factor=2.0)
    window = [_span() for _ in range(5)]

    anomalies = detector.check(window, baseline_count=2)

    assert [a.kind for a in anomalies] == ["call_rate_spike"]
    assert anomalies[0].observed == pytest.approx(5.0)
    assert anomalies[0].limit == pytest.approx(4.0)


def test_spike_rule_needs_explicit_baseline() -> None:
    # No baseline supplied -> the rate rule is skipped (no internal clock).
    detector = AnomalyDetector(spike_factor=2.0)
    assert detector.check([_span() for _ in range(100)]) == []


def test_multiple_rules_can_fire_in_one_window() -> None:
    detector = AnomalyDetector(
        span_cost_ceiling=1.0,
        budget_caps={("domain", "d1"): 1.0},
        spike_factor=1.0,
    )
    window = [_span(domain="d1", cost=2.0), _span(domain="d1", cost=2.0)]

    kinds = sorted(a.kind for a in detector.check(window, baseline_count=1))

    assert kinds == ["budget_cap", "call_rate_spike", "cost_ceiling", "cost_ceiling"]


def test_spike_factor_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AnomalyDetector(spike_factor=0.0)
