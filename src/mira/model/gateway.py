"""Provider-agnostic model gateway (ADR-010).

The gateway is the single seam every model call passes through. By default it
delegates straight to the LLM from an injected :class:`ProviderBundle`, keeping
callers (and the LangGraph adapter) free of vendor SDKs.

When wired for resilience (ADR-011/ADR-042) it composes:

- a :class:`~mira.model.routing.Router` to pick a provider/model per call,
- a :class:`~mira.model.fallback.FallbackChain` (with circuit breakers) to rotate
  providers on 5xx/timeout, downgrade on 429/budget, and isolate dead providers,
- a :class:`~mira.model.routing.SpanObserver` that receives one
  :class:`~mira.model.routing.CostLatencySpan` per completed call.

Composition is opt-in: with no router/fallback configured the gateway behaves
exactly as before, so existing callers are unaffected.
"""

from __future__ import annotations

import time
from typing import Callable

from mira.model.fallback import FallbackChain
from mira.model.routing import BudgetCap, CostLatencySpan, ModelRoute, Router, SpanObserver
from mira.providers.bundle import ProviderBundle
from mira.providers.protocols import ILLMProvider


class Gateway:
    """Central model gateway implementing ``ILLMProvider``.

    Delegates to the LLM implementation from an injected provider bundle so
    callers (and the LangGraph adapter) never import a vendor SDK. When a
    ``router`` and/or ``fallback_chain`` are supplied, completions route through
    them and each call emits a cost/latency span to ``span_observer``.
    """

    def __init__(
        self,
        bundle: ProviderBundle,
        *,
        router: Router | None = None,
        fallback_chain: FallbackChain | None = None,
        span_observer: SpanObserver | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._backend: ILLMProvider = bundle.llm
        self._router = router
        self._fallback_chain = fallback_chain
        self._span_observer = span_observer
        self._clock = clock or time.monotonic

    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        tenant: str = "default",
        agent: str = "default",
        budget_cap: BudgetCap | None = None,
    ) -> str:
        # Backward-compatible fast path: no resilience wiring -> delegate as before.
        if self._router is None and self._fallback_chain is None:
            return self._backend.complete(prompt, model=model)

        # The router is a real gate: select() enforces strategy + budget caps and
        # raises BudgetExceeded (when on_exceed="reject") or downgrades to an
        # affordable route. We let that propagate — the call is rejected before it
        # runs — and use the selected route as the actual call path + span label.
        route = self._select_route(
            model=model, tenant=tenant, agent=agent, budget_cap=budget_cap
        )
        started = self._clock()
        try:
            result = self._run(prompt, model=model, route=route)
        finally:
            self._emit_span(route, latency_ms=(self._clock() - started) * 1000.0)
        return result

    def embed(self, text: str) -> list[float]:
        return self._backend.embed(text)

    def _run(self, prompt: str, *, model: str | None, route: ModelRoute | None) -> str:
        """Execute the completion on the routed model, via the fallback chain when
        configured. The routed model takes precedence over an explicit ``model``
        so the gateway honors the budget-aware selection."""
        chosen_model = route.model if route is not None else model
        if self._fallback_chain is not None:
            return self._fallback_chain.complete(prompt, model=chosen_model)
        return self._backend.complete(prompt, model=chosen_model)

    def _select_route(
        self,
        *,
        model: str | None,
        tenant: str,
        agent: str,
        budget_cap: BudgetCap | None,
    ) -> ModelRoute | None:
        """Select a route, enforcing budget caps. ``BudgetExceeded`` propagates
        (the call is gated, not silently degraded). Returns ``None`` only when no
        router is configured (fallback-only path)."""
        if self._router is None:
            return None
        return self._router.select(tenant=tenant, agent=agent, budget_cap=budget_cap)

    def _emit_span(self, route: ModelRoute | None, *, latency_ms: float) -> None:
        if self._span_observer is None:
            return
        if route is not None:
            cost = route.cost_per_1k_tokens
            provider, model_name = route.provider, route.model
        else:
            cost = 0.0
            provider, model_name = "gateway", "default"
        self._span_observer.emit(
            CostLatencySpan(
                provider=provider,
                model=model_name,
                cost=cost,
                latency_ms=latency_ms,
            )
        )
