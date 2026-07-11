"""Resilience composition tests for the model gateway (e04-f05, ADR-011/ADR-042).

These exercise the *Gateway* seam (not the chain/router in isolation): provider
rotation on 5xx, model downgrade on 429/budget, circuit-breaker isolation of a
dead provider, and one cost/latency span emitted per call through an injected
``SpanObserver``. The no-config backward-compatible path is also pinned.
"""

from __future__ import annotations

from mira.model.fallback import (
    FallbackChain,
    FallbackPolicy,
    ProviderSlot,
    RetryableProviderError,
    ThrottleError,
)
from mira.model.gateway import Gateway
from mira.model.routing import (
    BudgetCap,
    BudgetExceeded,
    BudgetTracker,
    CostLatencySpan,
    ModelRoute,
    Router,
    RoutingStrategy,
)
from mira.providers.protocols import ILLMProvider


class FakeLLMProvider:
    """Bundle-default backend used for the no-config delegation path."""

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        suffix = f" model={model}" if model else ""
        return f"fake:{prompt}{suffix}"

    def embed(self, text: str) -> list[float]:
        return [float(len(text))]


class FakeBundle:
    def __init__(self, llm: ILLMProvider) -> None:
        self.llm = llm


class ScriptingProvider:
    """Provider that replays a scripted sequence of results/exceptions."""

    def __init__(self, script: list[Exception | str]) -> None:
        self._script = list(script)
        self.calls = 0

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        self.calls += 1
        if not self._script:
            return f"ok:{prompt}"
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def embed(self, text: str) -> list[float]:
        return [1.0]


class RecordingObserver:
    def __init__(self) -> None:
        self.spans: list[CostLatencySpan] = []

    def emit(self, span: CostLatencySpan) -> None:
        self.spans.append(span)


def _slot(name: str, script: list[Exception | str]) -> ProviderSlot:
    return ProviderSlot(name=name, provider=ScriptingProvider(script))


def _bundle() -> FakeBundle:
    return FakeBundle(FakeLLMProvider())


def _ticking_clock(values: list[float]):
    """Return a clock that yields successive values (start, end, ...)."""
    seq = iter(values)
    return lambda: next(seq)


def test_no_config_delegates_to_bundle() -> None:
    # Backward compatible: without router/fallback the gateway delegates to bundle.llm.
    gateway = Gateway(_bundle())
    assert gateway.complete("hi", model="m") == "fake:hi model=m"
    assert gateway.embed("abc") == [3.0]


def test_gateway_rotates_provider_on_5xx() -> None:
    chain = FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")]),
        fallbacks=[_slot("fallback", ["fallback-ok"])],
        policy=FallbackPolicy(max_retries=0),
    )
    gateway = Gateway(_bundle(), fallback_chain=chain)
    assert gateway.complete("rotate") == "fallback-ok"


def test_gateway_downgrades_on_throttle() -> None:
    chain = FallbackChain(
        primary=_slot("primary", [ThrottleError("429")]),
        downgrade=_slot("cheap", ["downgraded"]),
        policy=FallbackPolicy(max_retries=0),
    )
    gateway = Gateway(_bundle(), fallback_chain=chain)
    assert gateway.complete("expensive") == "downgraded"


def test_gateway_breaker_isolates_dead_provider() -> None:
    # An already-open breaker on the first fallback means that provider is never
    # invoked; the chain skips it and the healthy provider serves the call.
    dead = _slot("dead", [RetryableProviderError("503")])
    healthy = _slot("healthy", ["healthy-ok"])
    chain = FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")]),
        fallbacks=[dead, healthy],
        policy=FallbackPolicy(max_retries=0, failure_threshold=1),
    )
    chain.breaker_for("dead").record_failure()  # trip the dead provider's breaker
    gateway = Gateway(_bundle(), fallback_chain=chain)

    assert gateway.complete("isolate") == "healthy-ok"
    assert dead.provider.calls == 0  # isolated: never called
    assert healthy.provider.calls == 1
    assert chain.breaker_for("dead").state == "open"


def test_gateway_emits_one_span_per_call() -> None:
    observer = RecordingObserver()
    route = ModelRoute(provider="anthropic", model="claude", cost_per_1k_tokens=0.5)
    router = Router(strategy=RoutingStrategy.COST, routes=[route])
    chain = FallbackChain(
        primary=_slot("primary", ["ok"]),
        policy=FallbackPolicy(max_retries=0),
    )
    gateway = Gateway(
        _bundle(),
        router=router,
        fallback_chain=chain,
        span_observer=observer,
        clock=_ticking_clock([10.0, 10.25]),  # 0.25s -> 250ms latency
    )

    assert gateway.complete("measure") == "ok"
    assert len(observer.spans) == 1
    span = observer.spans[0]
    assert span.provider == "anthropic"
    assert span.model == "claude"
    assert span.cost == 0.5
    assert span.latency_ms == 250.0


def test_gateway_emits_span_even_when_call_fails() -> None:
    # The span is emitted in a finally block, so observability survives failures.
    observer = RecordingObserver()
    router = Router(
        strategy=RoutingStrategy.COST,
        routes=[ModelRoute(provider="p", model="m", cost_per_1k_tokens=1.0)],
    )
    chain = FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")]),
        policy=FallbackPolicy(max_retries=0),
    )
    gateway = Gateway(
        _bundle(),
        router=router,
        fallback_chain=chain,
        span_observer=observer,
        clock=_ticking_clock([0.0, 0.1]),
    )

    raised = False
    try:
        gateway.complete("will-fail")
    except Exception:
        raised = True
    assert raised
    assert len(observer.spans) == 1
    assert observer.spans[0].latency_ms == 100.0


def test_gateway_routes_through_fallback_without_router() -> None:
    # Fallback alone (no router) still works; span attribution falls back to a
    # synthetic gateway/default label.
    observer = RecordingObserver()
    chain = FallbackChain(
        primary=_slot("primary", ["primary-ok"]),
        policy=FallbackPolicy(max_retries=0),
    )
    gateway = Gateway(
        _bundle(),
        fallback_chain=chain,
        span_observer=observer,
        clock=_ticking_clock([0.0, 0.05]),
    )

    assert gateway.complete("no-router") == "primary-ok"
    assert len(observer.spans) == 1
    assert observer.spans[0].provider == "gateway"
    assert observer.spans[0].latency_ms == 50.0


def test_gateway_rejects_when_budget_exceeded() -> None:
    # M1 fix: the Router is a real gate. A tenant already over its BudgetCap
    # (on_exceed="reject") must have the call REJECTED at the gateway — not run.
    tracker = BudgetTracker()
    tracker.record("acme", "agent-1", 100.0)  # already well over the cap
    router = Router(
        strategy=RoutingStrategy.COST,
        routes=[ModelRoute(provider="anthropic", model="claude", cost_per_1k_tokens=5.0)],
        budget_tracker=tracker,
    )
    backend = ScriptingProvider(["should-not-run"])
    chain = FallbackChain(primary=_slot("primary", ["should-not-run"]), policy=FallbackPolicy(max_retries=0))
    gateway = Gateway(
        FakeBundle(backend), router=router, fallback_chain=chain,
        clock=_ticking_clock([0.0, 0.01]),
    )

    raised = False
    try:
        gateway.complete("expensive", tenant="acme", agent="agent-1",
                         budget_cap=BudgetCap(max_cost=1.0, on_exceed="reject"))
    except BudgetExceeded:
        raised = True
    assert raised, "gateway must reject a call that exceeds the budget cap"
    assert backend.calls == 0, "the rejected call must never reach the provider"


def test_gateway_downgrades_to_affordable_route_on_budget() -> None:
    # on_exceed="downgrade": over budget for the premium route -> the gateway
    # runs the cheaper affordable route (budget gating actually selects it).
    tracker = BudgetTracker()
    tracker.record("acme", "agent-1", 0.6)  # leaves 0.4 of a 1.0 cap
    router = Router(
        strategy=RoutingStrategy.COST,
        routes=[
            ModelRoute(provider="prem", model="premium", cost_per_1k_tokens=5.0),
            ModelRoute(provider="cheap", model="mini", cost_per_1k_tokens=0.2),
        ],
        budget_tracker=tracker,
    )
    # the fallback chain echoes which model it was asked to run
    backend = ScriptingProvider([])
    chain = FallbackChain(
        primary=ProviderSlot("primary", _EchoModelProvider()),
        policy=FallbackPolicy(max_retries=0),
    )
    gateway = Gateway(FakeBundle(backend), router=router, fallback_chain=chain,
                      clock=_ticking_clock([0.0, 0.01]))

    result = gateway.complete("q", tenant="acme", agent="agent-1",
                              budget_cap=BudgetCap(max_cost=1.0, on_exceed="downgrade"))
    assert result == "ran:mini", "gateway must run the budget-affordable (cheaper) route"


class _EchoModelProvider:
    """Provider that reports which model it was asked to run (for downgrade assertion)."""

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        return f"ran:{model}"

    def embed(self, text: str) -> list[float]:
        return [0.0]


# --- ADR-052: tier-aware gateway ---------------------------------------------


class ModelRecordingProvider:
    """Backend that records the model= it was asked for, for both call shapes."""

    def __init__(self) -> None:
        self.completed_with: list[str | None] = []
        self.chatted_with: list[str | None] = []

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        self.completed_with.append(model)
        return f"ok:{model}"

    def chat(self, messages, *, model=None, tools=None, tool_choice="auto"):
        self.chatted_with.append(model)

        class _Result:
            text = f"chat-ok:{model}"
            tool_calls = ()

        return _Result()

    def embed(self, text: str) -> list[float]:
        return [1.0]


def _tiered_gateway(backend, **kwargs) -> Gateway:
    from mira.model.tiering import TierPolicy

    routes = [
        ModelRoute("d", "cheap-model", cost_per_1k_tokens=0.3, tier="light"),
        ModelRoute("d", "deep-model", cost_per_1k_tokens=2.2, tier="deep"),
    ]
    policy = TierPolicy(
        agent_tiers={"advisor": "deep"}, classifier=lambda prompt: "light"
    )
    return Gateway(
        FakeBundle(backend),  # type: ignore[arg-type]
        router=Router(strategy=RoutingStrategy.COST, routes=routes),
        tier_policy=policy,
        **kwargs,
    )


def test_no_config_gateway_ignores_tier_kwarg():
    backend = FakeLLMProvider()
    gateway = Gateway(FakeBundle(backend))  # type: ignore[arg-type]
    assert gateway.complete("hi", tier="deep") == "fake:hi"


def test_tier_resolution_explicit_beats_agent_hint_beats_heuristic():
    backend = ModelRecordingProvider()
    gateway = _tiered_gateway(backend)
    gateway.complete("q")  # heuristic -> light
    gateway.complete("q", agent="advisor")  # hint -> deep
    gateway.complete("q", agent="advisor", tier="light")  # explicit wins
    assert backend.completed_with == ["cheap-model", "deep-model", "cheap-model"]


def test_for_agent_binds_identity_for_complete_and_chat():
    backend = ModelRecordingProvider()
    gateway = _tiered_gateway(backend)
    bound = gateway.for_agent("advisor")
    bound.complete("q")
    bound.chat([{"role": "user", "content": "q"}])
    assert backend.completed_with == ["deep-model"]
    assert backend.chatted_with == ["deep-model"]


def test_chat_routes_and_emits_span():
    backend = ModelRecordingProvider()
    observer = RecordingObserver()
    gateway = _tiered_gateway(backend, span_observer=observer)
    result = gateway.chat([{"role": "user", "content": "q"}], agent="advisor")
    assert result.text == "chat-ok:deep-model"
    assert [span.model for span in observer.spans] == ["deep-model"]


def test_chat_on_text_only_backend_degrades_to_routed_completion():
    backend = ScriptingProvider([])  # has complete, no chat
    gateway = Gateway(
        FakeBundle(backend),  # type: ignore[arg-type]
        router=Router(
            strategy=RoutingStrategy.COST,
            routes=[ModelRoute("d", "cheap-model", cost_per_1k_tokens=0.3, tier="light")],
        ),
    )
    result = gateway.chat([{"role": "user", "content": "hello"}])
    assert result.text.startswith("ok:")
    assert result.tool_calls == ()
