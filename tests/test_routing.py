"""Unit tests for cost/quota routing (ADR-011)."""

from __future__ import annotations

import pytest

from mira.model.routing import (
    BudgetCap,
    BudgetExceeded,
    BudgetTracker,
    CostLatencySpan,
    ModelRoute,
    Router,
    RoutingStrategy,
)


def _routes() -> list[ModelRoute]:
    return [
        ModelRoute("openai", "gpt-4o", cost_per_1k_tokens=5.0, latency_ms_p50=800.0, quota_remaining=100),
        ModelRoute("anthropic", "claude-haiku", cost_per_1k_tokens=1.0, latency_ms_p50=400.0, quota_remaining=500),
        ModelRoute("google", "gemini-flash", cost_per_1k_tokens=0.5, latency_ms_p50=300.0, quota_remaining=1000),
    ]


def test_cost_strategy_selects_cheapest_first():
    router = Router(strategy=RoutingStrategy.COST, routes=_routes())
    selected = router.select()
    assert selected.provider == "google"
    assert selected.model == "gemini-flash"


def test_latency_strategy_selects_fastest_first():
    router = Router(strategy=RoutingStrategy.LATENCY, routes=_routes())
    selected = router.select()
    assert selected.provider == "google"
    assert selected.latency_ms_p50 == 300.0


def test_quota_strategy_selects_highest_remaining_quota():
    router = Router(strategy=RoutingStrategy.QUOTA, routes=_routes())
    selected = router.select()
    assert selected.provider == "google"
    assert selected.quota_remaining == 1000


def test_budget_cap_downgrades_to_affordable_route():
    tracker = BudgetTracker()
    tracker.record("t1", "a1", 9.5)
    cap = BudgetCap(max_cost=10.0, on_exceed="downgrade")
    router = Router(strategy=RoutingStrategy.COST, routes=_routes(), budget_tracker=tracker)
    selected = router.select(tenant="t1", agent="a1", budget_cap=cap)
    assert selected.cost_per_1k_tokens <= 0.5


def test_budget_cap_rejects_when_policy_is_reject():
    tracker = BudgetTracker()
    tracker.record("t1", "a1", 10.0)
    cap = BudgetCap(max_cost=10.0, on_exceed="reject")
    router = Router(strategy=RoutingStrategy.COST, routes=_routes(), budget_tracker=tracker)
    with pytest.raises(BudgetExceeded):
        router.select(tenant="t1", agent="a1", budget_cap=cap)


def test_record_call_emits_cost_latency_span():
    emitted: list[CostLatencySpan] = []

    class _Observer:
        def emit(self, span: CostLatencySpan) -> None:
            emitted.append(span)

    route = ModelRoute("openai", "gpt-4o-mini", cost_per_1k_tokens=2.0)
    router = Router(routes=[route], span_observer=_Observer())
    span = router.record_call(route, latency_ms=120.0, token_count=2000.0)
    assert span.cost == pytest.approx(4.0)
    assert span.latency_ms == 120.0
    assert len(emitted) == 1
    assert emitted[0].provider == "openai"
    assert emitted[0].model == "gpt-4o-mini"


# --- Negative-path and regression tests (review L1/H2/M2) ---


def test_select_raises_on_empty_routes():
    router = Router(strategy=RoutingStrategy.COST, routes=[])
    with pytest.raises(ValueError, match="no routes"):
        router.select()


def test_downgrade_raises_when_no_affordable_route():
    tracker = BudgetTracker()
    tracker.record("t1", "a1", 9.99)
    cap = BudgetCap(max_cost=10.0, on_exceed="downgrade")
    # cheapest route (0.5/1k) at 1000 tokens costs 0.5 > remaining 0.01
    router = Router(strategy=RoutingStrategy.COST, routes=_routes(), budget_tracker=tracker)
    with pytest.raises(BudgetExceeded, match="within remaining budget"):
        router.select(tenant="t1", agent="a1", budget_cap=cap)


def test_quota_tiebreak_when_remaining_is_none():
    routes = [
        ModelRoute("p1", "m1", cost_per_1k_tokens=2.0, quota_remaining=None),
        ModelRoute("p2", "m2", cost_per_1k_tokens=1.0, quota_remaining=None),
    ]
    router = Router(strategy=RoutingStrategy.QUOTA, routes=routes)
    # both unlimited (None) -> tie broken by cheaper cost
    assert router.select().provider == "p2"


def test_select_budget_uses_same_cost_units_as_record_call():
    # Regression for H2: pre-check must use the per-1k formula, not assume 1k.
    tracker = BudgetTracker()
    cap = BudgetCap(max_cost=10.0, on_exceed="reject")
    route = ModelRoute("p", "m", cost_per_1k_tokens=4.0)
    router = Router(routes=[route], budget_tracker=tracker)

    # 5000 tokens -> estimated 4.0 * 5 = 20.0 > cap 10.0 -> reject before the call
    with pytest.raises(BudgetExceeded):
        router.select(budget_cap=cap, estimated_tokens=5000.0)

    # 1000 tokens -> estimated 4.0 <= cap -> allowed
    assert router.select(budget_cap=cap, estimated_tokens=1000.0).provider == "p"


def test_budget_cap_rejects_invalid_on_exceed():
    with pytest.raises(ValueError, match="on_exceed"):
        BudgetCap(max_cost=1.0, on_exceed="rejectt")  # type: ignore[arg-type]


def test_budget_tracker_window_isolates_spend():
    tracker = BudgetTracker()
    tracker.record("t", "a", 5.0, window="2026-06-29")
    assert tracker.spent("t", "a", window="2026-06-29") == 5.0
    assert tracker.spent("t", "a", window="2026-06-30") == 0.0


# --- ADR-052: tier-aware selection ------------------------------------------


def _tiered_routes() -> list[ModelRoute]:
    return [
        ModelRoute("deepseek", "deepseek-chat", cost_per_1k_tokens=0.3, tier="light"),
        ModelRoute("deepseek", "deepseek-reasoner", cost_per_1k_tokens=2.2, tier="deep"),
        ModelRoute("deepseek", "deepseek-v3", cost_per_1k_tokens=1.0, tier="standard"),
    ]


def test_tier_preference_partitions_matching_routes_first():
    router = Router(strategy=RoutingStrategy.COST, routes=_tiered_routes())
    assert router.select(tier="deep").model == "deepseek-reasoner"
    assert router.select(tier="standard").model == "deepseek-v3"
    # No tier requested -> plain strategy ranking (cheapest).
    assert router.select().model == "deepseek-chat"


def test_missing_tier_falls_back_to_full_ranking():
    router = Router(strategy=RoutingStrategy.COST, routes=_tiered_routes())
    assert router.select(tier="colossal").model == "deepseek-chat"


def test_budget_downgrade_crosses_tiers():
    """Budget beats capability: an unaffordable deep tier degrades to any
    affordable route, tier notwithstanding (ADR-052)."""
    tracker = BudgetTracker()
    tracker.record("t1", "a1", 9.5)  # remaining 0.5 affords light (0.3), not deep (2.2)
    cap = BudgetCap(max_cost=10.0, on_exceed="downgrade")
    router = Router(
        strategy=RoutingStrategy.COST, routes=_tiered_routes(), budget_tracker=tracker
    )
    selected = router.select(tenant="t1", agent="a1", budget_cap=cap, tier="deep")
    assert selected.model == "deepseek-chat"  # cheapest affordable, not the deep route


def test_budget_reject_still_raises_with_tier():
    tracker = BudgetTracker()
    tracker.record("t1", "a1", 10.0)
    cap = BudgetCap(max_cost=10.0, on_exceed="reject")
    router = Router(
        strategy=RoutingStrategy.COST, routes=_tiered_routes(), budget_tracker=tracker
    )
    with pytest.raises(BudgetExceeded):
        router.select(tenant="t1", agent="a1", budget_cap=cap, tier="deep")
