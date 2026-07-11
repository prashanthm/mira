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
from typing import Any, Callable

from mira.model.fallback import FallbackChain
from mira.model.routing import BudgetCap, CostLatencySpan, ModelRoute, Router, SpanObserver
from mira.model.tiering import TierPolicy
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
        tier_policy: TierPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._backend: ILLMProvider = bundle.llm
        self._router = router
        self._fallback_chain = fallback_chain
        self._span_observer = span_observer
        self._tier_policy = tier_policy
        self._clock = clock or time.monotonic

    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        tenant: str = "default",
        agent: str = "default",
        budget_cap: BudgetCap | None = None,
        tier: str | None = None,
    ) -> str:
        # Backward-compatible fast path: no resilience wiring -> delegate as before.
        if self._router is None and self._fallback_chain is None:
            return self._backend.complete(prompt, model=model)

        # The router is a real gate: select() enforces strategy + budget caps and
        # raises BudgetExceeded (when on_exceed="reject") or downgrades to an
        # affordable route. We let that propagate — the call is rejected before it
        # runs — and use the selected route as the actual call path + span label.
        route = self._select_route(
            prompt, model=model, tenant=tenant, agent=agent, budget_cap=budget_cap, tier=tier
        )
        started = self._clock()
        try:
            result = self._run(prompt, model=model, route=route)
        finally:
            self._emit_span(route, latency_ms=(self._clock() - started) * 1000.0)
        return result

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        tenant: str = "default",
        agent: str = "default",
        budget_cap: BudgetCap | None = None,
        tier: str | None = None,
    ) -> Any:
        """Tool-aware chat turn, routed exactly like :meth:`complete` (ADR-052).

        Delegates to the backend's ``chat`` when it has one (the ADR-010
        provider seam). A backend without ``chat`` (e.g. the echo provider)
        degrades to a routed text completion with no tool calls — the same
        text-only semantics ``GatewayChatModel`` applied before this method
        existed, when the gateway itself failed the ``getattr`` probe and
        routed models silently never reached the tool path.
        """
        prompt = " ".join(
            str(message.get("content") or "") for message in messages
        ).strip()

        backend_chat = getattr(self._backend, "chat", None)
        if backend_chat is None:
            text = self.complete(
                prompt, model=model, tenant=tenant, agent=agent,
                budget_cap=budget_cap, tier=tier,
            )
            return _TextOnlyChatResult(text=text)

        if self._router is None:
            return backend_chat(messages, model=model, tools=tools, tool_choice=tool_choice)

        route = self._select_route(
            prompt, model=model, tenant=tenant, agent=agent, budget_cap=budget_cap, tier=tier
        )
        chosen_model = route.model if route is not None else model
        started = self._clock()
        try:
            return backend_chat(
                messages, model=chosen_model, tools=tools, tool_choice=tool_choice
            )
        finally:
            self._emit_span(route, latency_ms=(self._clock() - started) * 1000.0)

    def for_agent(self, name: str) -> _AgentBoundLLM:
        """An ``ILLMProvider``-shaped view that forwards ``agent=name`` (ADR-052).

        Lets call sites that only know the provider protocol (the runtime, the
        LangGraph adapter) carry agent identity into tier resolution without
        widening the protocol.
        """
        return _AgentBoundLLM(self, name)

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
        prompt: str,
        *,
        model: str | None,
        tenant: str,
        agent: str,
        budget_cap: BudgetCap | None,
        tier: str | None = None,
    ) -> ModelRoute | None:
        """Select a route, enforcing budget caps. ``BudgetExceeded`` propagates
        (the call is gated, not silently degraded). Returns ``None`` only when no
        router is configured (fallback-only path). Tier resolution (ADR-052):
        explicit ``tier`` > agent hint > difficulty heuristic, via the policy."""
        if self._router is None:
            return None
        resolved_tier = tier
        if self._tier_policy is not None:
            resolved_tier = self._tier_policy.resolve(prompt, agent=agent, explicit=tier)
        return self._router.select(
            tenant=tenant, agent=agent, budget_cap=budget_cap, tier=resolved_tier
        )

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


class _TextOnlyChatResult:
    """Duck-typed ``ChatResult`` (``.text`` / ``.tool_calls``) for text-only backends."""

    __slots__ = ("text", "tool_calls")

    def __init__(self, *, text: str) -> None:
        self.text = text
        self.tool_calls: tuple[Any, ...] = ()


class _AgentBoundLLM:
    """An ``ILLMProvider``-shaped view of a gateway bound to one agent identity.

    ``complete``/``embed`` satisfy the protocol; ``chat`` is exposed so the
    LangGraph adapter's ``getattr(llm, "chat", None)`` probe finds the routed
    tool path when the backend supports it. ``tier`` may still be forced
    per-call (e.g. by model-tier escalation) and wins over the agent hint.
    """

    def __init__(self, gateway: Gateway, agent: str) -> None:
        self._gateway = gateway
        self._agent = agent

    def complete(
        self, prompt: str, *, model: str | None = None, tier: str | None = None
    ) -> str:
        return self._gateway.complete(prompt, model=model, agent=self._agent, tier=tier)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        tier: str | None = None,
    ) -> Any:
        return self._gateway.chat(
            messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            agent=self._agent,
            tier=tier,
        )

    def embed(self, text: str) -> list[float]:
        return self._gateway.embed(text)
