"""Cost/quota-aware model routing (ADR-011)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Protocol

OnExceed = Literal["downgrade", "reject"]


class RoutingStrategy(str, Enum):
    """Strategy for selecting provider/model per request."""

    COST = "cost"
    LATENCY = "latency"
    QUOTA = "quota"


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """A routable provider/model pair with cost and latency metadata.

    ``tier`` is an optional capability class (ADR-052, e.g. ``light``/
    ``standard``/``deep``); empty means untiered. Tier is a selection
    *preference*, orthogonal to the ranking strategy.
    """

    provider: str
    model: str
    cost_per_1k_tokens: float = 0.0
    latency_ms_p50: float = 0.0
    quota_remaining: int | None = None
    tier: str = ""


class BudgetExceeded(Exception):
    """Raised when a budget cap is exceeded and policy is reject."""


@dataclass(frozen=True, slots=True)
class BudgetCap:
    """Per-tenant/agent budget limit and exceed policy."""

    max_cost: float
    on_exceed: OnExceed = "downgrade"

    def __post_init__(self) -> None:
        if self.on_exceed not in ("downgrade", "reject"):
            raise ValueError(
                f"on_exceed must be 'downgrade' or 'reject', got {self.on_exceed!r}"
            )


class BudgetTracker:
    """Track spend per tenant/agent/window.

    ``window`` is an opaque caller-supplied identifier (e.g. a day bucket or
    billing period). Spend is keyed by it so per-window caps (ADR-011) can be
    enforced; the default single window preserves cumulative behavior. To reset
    a window, call :meth:`reset` (or simply use a new window id).
    """

    def __init__(self) -> None:
        self._spend: dict[tuple[str, str, str], float] = {}

    def record(self, tenant: str, agent: str, cost: float, *, window: str = "default") -> None:
        key = (tenant, agent, window)
        self._spend[key] = self._spend.get(key, 0.0) + cost

    def spent(self, tenant: str, agent: str, *, window: str = "default") -> float:
        return self._spend.get((tenant, agent, window), 0.0)

    def reset(self, tenant: str, agent: str, *, window: str = "default") -> None:
        self._spend.pop((tenant, agent, window), None)

    def would_exceed(
        self,
        tenant: str,
        agent: str,
        cap: BudgetCap,
        incremental: float,
        *,
        window: str = "default",
    ) -> bool:
        return self.spent(tenant, agent, window=window) + incremental > cap.max_cost


@dataclass(frozen=True, slots=True)
class CostLatencySpan:
    """OTel-shaped cost/latency observation for a model call."""

    provider: str
    model: str
    cost: float
    latency_ms: float


class SpanObserver(Protocol):
    """Injectable observer for cost/latency spans (ADR-042)."""

    def emit(self, span: CostLatencySpan) -> None:
        """Record a cost/latency span for a completed call."""


def _rank_routes(strategy: RoutingStrategy, routes: list[ModelRoute]) -> list[ModelRoute]:
    if strategy is RoutingStrategy.COST:
        return sorted(routes, key=lambda r: (r.cost_per_1k_tokens, r.latency_ms_p50))
    if strategy is RoutingStrategy.LATENCY:
        return sorted(routes, key=lambda r: (r.latency_ms_p50, r.cost_per_1k_tokens))
    # QUOTA: prefer routes with highest remaining quota; None treated as unlimited (last).
    return sorted(
        routes,
        key=lambda r: (
            r.quota_remaining is None,
            -(r.quota_remaining or 0),
            r.cost_per_1k_tokens,
        ),
    )


@dataclass
class Router:
    """Select provider/model by routing strategy with optional budget enforcement."""

    strategy: RoutingStrategy = RoutingStrategy.COST
    routes: list[ModelRoute] | None = None
    budget_tracker: BudgetTracker | None = None
    span_observer: SpanObserver | None = None

    def __post_init__(self) -> None:
        if self.routes is None:
            self.routes = []

    @staticmethod
    def _estimated_cost(route: ModelRoute, estimated_tokens: float) -> float:
        """Cost estimate using the SAME formula as record_call (per-1k tokens)."""
        return route.cost_per_1k_tokens * (estimated_tokens / 1000.0)

    def select(
        self,
        *,
        tenant: str = "default",
        agent: str = "default",
        budget_cap: BudgetCap | None = None,
        estimated_tokens: float = 1000.0,
        window: str = "default",
        tier: str | None = None,
    ) -> ModelRoute:
        """Choose provider/model per strategy; downgrade or reject on budget exceed.

        ``tier`` (ADR-052) is a capability preference: tier-matching routes are
        stably partitioned ahead of the rest *after* strategy ranking, so a
        requested tier wins when available and selection degrades to the plain
        ranking when it is not — capability never makes selection fail. The
        budget gate runs over that ordering and its downgrade search spans the
        full ranked list, so budget caps beat capability by construction.

        Budget gating estimates this call's cost via ``estimated_tokens`` using
        the same per-1k-token formula as :meth:`record_call`, so a route cannot
        pass ``select`` gating and then overspend on the recorded call.
        """
        if not self.routes:
            raise ValueError("Router has no routes configured")

        ranked = _rank_routes(self.strategy, list(self.routes))
        if tier:
            ranked = [r for r in ranked if r.tier == tier] + [
                r for r in ranked if r.tier != tier
            ]
        primary = ranked[0]

        if budget_cap is None or self.budget_tracker is None:
            return primary

        incremental = self._estimated_cost(primary, estimated_tokens)
        if not self.budget_tracker.would_exceed(
            tenant, agent, budget_cap, incremental, window=window
        ):
            return primary

        if budget_cap.on_exceed == "reject":
            raise BudgetExceeded(
                f"Budget cap {budget_cap.max_cost} exceeded for tenant={tenant!r} agent={agent!r}"
            )

        # Downgrade: pick the cheapest route whose estimated cost fits the
        # remaining budget (same cost basis as the pre-check above).
        remaining = budget_cap.max_cost - self.budget_tracker.spent(
            tenant, agent, window=window
        )
        affordable = [
            r for r in ranked if self._estimated_cost(r, estimated_tokens) <= remaining
        ]
        if not affordable:
            raise BudgetExceeded(
                f"No route within remaining budget {remaining} for tenant={tenant!r} agent={agent!r}"
            )
        return affordable[0]

    def record_call(
        self,
        route: ModelRoute,
        *,
        tenant: str = "default",
        agent: str = "default",
        latency_ms: float,
        token_count: float = 1.0,
        window: str = "default",
    ) -> CostLatencySpan:
        """Record spend and emit a cost/latency span for a completed call."""
        cost = route.cost_per_1k_tokens * (token_count / 1000.0)
        if self.budget_tracker is not None:
            self.budget_tracker.record(tenant, agent, cost, window=window)

        span = CostLatencySpan(
            provider=route.provider,
            model=route.model,
            cost=cost,
            latency_ms=latency_ms,
        )
        if self.span_observer is not None:
            self.span_observer.emit(span)
        return span
