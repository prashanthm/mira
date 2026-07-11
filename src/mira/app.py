"""Composition root for the runnable agent service (e03-f07).

Wires the deployment profile (e05-f01) → provider bundle (ADR-002) →
``Gateway`` (e04-f01) → ``AgentRuntime`` (e03-f01) → ``WarmService`` (e03-f02)
into a single runnable app. No vendor SDK is imported at module-import time; the
provider bundle is resolved lazily through ``mira.providers.factory`` so the local
profile boots without any cloud/orchestration vendor SDK on the import path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from mira.config.profiles import Profile, load_profile
from mira.core.service import WarmService
from mira.core.streaming import OutputGuard, StreamEvent
from mira.core.streaming_sse import WSGIHandler, make_sse_handler
from mira.model.gateway import Gateway
from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.run_events import run_to_events, supervisor_to_events
from mira.orchestration.runtime import AgentRuntime
from mira.orchestration.supervisor import Supervisor
from mira.providers.bundle import ProviderBundle
from mira.providers.factory import get_providers

# A turn runner produces the run result dict for a prompt+thread; defaults to the
# runtime invoke that ``run_turn`` uses. Tests inject a runner whose result
# carries reasoning ``plan_steps`` to exercise the streamed plan end-to-end.
TurnRunner = Callable[[str, str], dict[str, Any]]

DEFAULT_PROFILE = "kubernetes"


@dataclass(frozen=True, slots=True)
class App:
    """A composed, runnable agent service.

    Bundles the :class:`WarmService` (health probes / drain) with the
    :class:`AgentRuntime` so the entrypoint can both serve health probes and run
    one end-to-end turn. ``run_turn`` is the "handler that runs a turn" the
    feature AC calls for.
    """

    profile: Profile
    bundle: ProviderBundle
    gateway: Gateway
    runtime: AgentRuntime
    service: WarmService
    # Optional supervisor (ADR-014) built from an agent-card registry: when
    # present, /turn routes supervisor-first (grounded specialist answers) and
    # falls back to the runtime turn only when no card matches.
    supervisor: Supervisor | None = None
    # Optional decision-trace store (ADR-040): supervisor-routed turns are
    # recorded under their correlation id so /explain can serve them (ADR-041).
    trace_store: Any = None

    @property
    def wsgi_app(self) -> Any:
        """WSGI callable serving the warm service health probes."""
        return self.service.wsgi_app

    def run_turn(self, prompt: str, *, thread_id: str = "default") -> dict[str, Any]:
        """Run one non-streaming end-to-end turn through the runtime.

        Tracked as in-flight work so a concurrent SIGTERM drain waits for it.
        """
        with self.service.track_in_flight():
            return self.runtime.invoke({"prompt": prompt}, thread_id=thread_id)

    def _default_runner(self, prompt: str, thread_id: str) -> dict[str, Any]:
        """Default turn source for streaming: the runtime invoke ``run_turn`` uses."""
        return self.runtime.invoke({"prompt": prompt}, thread_id=thread_id)

    def stream_events(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        runner: TurnRunner | None = None,
    ) -> Iterator[StreamEvent]:
        """Run one turn and yield its typed event stream (plan steps → done/error).

        Bracketed by :meth:`WarmService.track_in_flight` so a concurrent SIGTERM
        drain waits for an in-progress streamed turn (matching ``run_turn``). A
        run that raises is mapped to a terminal ``error`` event via
        :func:`run_to_events` rather than escaping, so the stream always
        terminates cleanly. The output guard is applied per-event on the SSE wire
        path (:meth:`stream_turn`), not here.
        """
        run = runner or self._default_runner
        with self.service.track_in_flight():
            try:
                result: dict[str, Any] | BaseException = run(prompt, thread_id)
            except Exception as exc:  # noqa: BLE001 — surfaced as a typed error event
                result = exc
            yield from run_to_events(result)

    def stream_turn(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        guard: OutputGuard | None = None,
        runner: TurnRunner | None = None,
    ) -> WSGIHandler:
        """Build a WSGI handler that streams one turn as ``text/event-stream``.

        Mounts the e03-f03-t02 :func:`make_sse_handler` over this turn's event
        stream, threading the per-chunk output ``guard`` through so guardrail-out
        runs before each frame leaves. This is the streaming endpoint the feature
        AC needs: boot the app, call the handler with a WSGI
        ``environ``/``start_response``, and the body yields ordered SSE frames
        (``plan_step``… → ``done``).
        """
        events = self.stream_events(prompt, thread_id=thread_id, runner=runner)
        return make_sse_handler(events, guard=guard)

    def turn_handler(self, prompt: str, thread_id: str) -> WSGIHandler:
        """The ``POST /turn`` factory the warm service delegates to (ADR-006 V1).

        Supervisor-first when a registry was provided at build time; otherwise
        (or when no agent card matches the prompt) the stream falls back to the
        default runtime turn — the same event source :meth:`stream_turn` uses.
        """
        return make_sse_handler(self._turn_events(prompt, thread_id))

    def _turn_events(self, prompt: str, thread_id: str) -> Iterator[StreamEvent]:
        """Supervisor-first event source for one /turn request.

        Bracketed by :meth:`WarmService.track_in_flight` (the nested entry taken
        by the fallback :meth:`stream_events` counts as its own unit, matching
        the drain semantics of a directly streamed turn). A supervisor failure
        maps to a terminal ``error`` event rather than escaping mid-stream.
        """
        if self.supervisor is None:
            yield from self.stream_events(prompt, thread_id=thread_id)
            return

        with self.service.track_in_flight():
            try:
                result = self.supervisor.invoke(prompt, thread_id=thread_id)
            except Exception as exc:  # noqa: BLE001 — surfaced as a typed error event
                yield from run_to_events(exc)
                return
            if result.routed_domain is not None:
                import uuid

                correlation_id = str(uuid.uuid4())
                self._record_turn_trace(correlation_id, result)
                yield from supervisor_to_events(result, correlation_id=correlation_id)
                return
            # No card matched: the supervisor never guesses a domain — fall back
            # to the runtime turn (echo/model path).
            yield from self.stream_events(prompt, thread_id=thread_id)

    def _record_turn_trace(self, correlation_id: str, result: Any) -> None:
        """Record a supervisor-routed turn in the decision-trace store (ADR-040).

        One record per specialist result, all under the turn's correlation id so
        ``GET /explain?correlation_id=…`` reconstructs the whole answer. Best
        effort: a trace failure must never break the user-facing stream.
        """
        if self.trace_store is None:
            return
        try:
            for index, specialist_result in enumerate(result.results):
                self.trace_store.record_from_result(
                    f"{correlation_id}:{index}", correlation_id, specialist_result
                )
        except Exception:  # noqa: BLE001 — tracing is observability, not the answer path
            pass


def build_app(
    profile: str | None = None,
    *,
    bundle: ProviderBundle | None = None,
    registry: AgentCardRegistry | None = None,
) -> App:
    """Build the runtime-behind-gateway composition from the deployment profile.

    Resolution order for the profile name: explicit ``profile`` arg, then
    ``DEPLOYMENT_PROFILE`` env (via :func:`load_profile`), then
    :data:`DEFAULT_PROFILE`. The provider bundle is resolved from the profile's
    ``platform`` unless an explicit ``bundle`` is injected (used by tests to
    supply a fake, network-free provider).

    An optional agent-card ``registry`` (ADR-035) turns on supervisor-first
    /turn routing (ADR-014): matched prompts are answered by the routed
    specialist, unmatched prompts fall back to the runtime turn. Without a
    registry the app behaves exactly as before.
    """
    resolved = load_profile(profile or _profile_name_or_default())
    if bundle is None:
        # An explicit PLATFORM env wins over the profile default so a local boot
        # (PLATFORM=local) resolves the in-memory bundle and never imports a
        # cloud SDK; otherwise fall back to the profile's platform.
        bundle = get_providers(_platform_or_default(resolved))

    tools = _discover_mcp_tools(resolved)

    # Advisor domain (ADR-014 Phase V3): when MCP discovery yielded a vantage.*
    # tool surface, bridge it and register the advisor card so /turn routes
    # portfolio queries to the MCP-backed specialist. Best-effort — failure
    # degrades to the registry as passed in, matching the discovery contract.
    registry = _registry_with_advisor(tools, registry)

    # Foreign CLI agent (ADR-051, optional): FOREIGN_AGENT_CMD names a command
    # that speaks the envelope→trace contract over stdin/stdout. Absent env ⇒
    # zero behavior change; failures degrade like advisor registration.
    registry = _registry_with_foreign(registry)

    # Tier-aware gateway (ADR-052, optional): MODEL_ROUTES turns on the router
    # with a TierPolicy derived from the registry's card model_hints; absent env
    # ⇒ Gateway(bundle) exactly as before. Built after registry enrichment so
    # advisor/foreign hints participate. General turns carry the "general" agent
    # identity, so un-hinted prompts resolve through the difficulty heuristic.
    gateway = _gateway_from_env(bundle, registry)
    runtime = AgentRuntime(gateway.for_agent("general"), bundle.state_store, tools=tools)

    # Model-tier escalation (ADR-052, double-flagged): only when tier routing is
    # configured AND the profile flag is on (ENABLE_TIER_ESCALATION) do
    # registered specialists get the one-retry escalating wrapper. The eval
    # registry never passes through here, so eval semantics are untouched.
    registry = _registry_with_tier_escalation(registry, resolved)

    supervisor = Supervisor(registry) if registry is not None else None

    # /insights (ADR-006 Phase V3): lazy, cached advisory reports per registered
    # domain. Reports generate on first request (a scheduled job hitting the
    # endpoint periodically keeps them warm); ?refresh=1 regenerates.
    insights_provider = None
    if registry is not None:
        from mira.orchestration.insights import cached_insights_provider

        insights_provider = cached_insights_provider(registry)

    # The service needs the /turn factory at construction time, but the factory
    # is a method of the App composed *around* the service — bind it through a
    # late-filled holder so the ctor-param contract holds without mutating the
    # frozen App.
    app_holder: list[App] = []

    def _turn_handler(prompt: str, thread_id: str) -> WSGIHandler:
        return app_holder[0].turn_handler(prompt, thread_id)

    # ADR-035: expose the routable registry as A2A discovery cards.
    agent_cards = None
    if registry is not None:
        cards_registry = registry
        agent_cards = lambda: [card.to_dict() for card in cards_registry.cards()]  # noqa: E731

    # ADR-040/041: supervisor-routed turns are recorded so /explain serves them.
    # The composition root is where the real clock is injected (the store itself
    # never defaults to wall time).
    trace_store = None
    if registry is not None:
        import time

        from mira.core.decision_trace import TraceStore

        trace_store = TraceStore(clock=time.time)

    service = WarmService(
        deps_ready=lambda: True,
        turn_handler=_turn_handler,
        insights_provider=insights_provider,
        agent_cards=agent_cards,
        trace_store=trace_store,
    )
    service.mark_startup_complete()

    app = App(
        profile=resolved,
        bundle=bundle,
        gateway=gateway,
        runtime=runtime,
        service=service,
        supervisor=supervisor,
        trace_store=trace_store,
    )
    app_holder.append(app)
    return app


def _discover_mcp_tools(profile: Profile) -> list[Any]:
    """Resolve the declared MCP registry and discover its tools at app-build time.

    Empty registry (no ``MCP_SERVERS`` / ``MCP_BASE_URL`` / profile ``mcp_endpoint``) ⇒
    ``[]``, so the agent runs exactly as before. Registry *parse* errors (malformed
    ``MCP_SERVERS``) are genuine misconfiguration and propagate. *Discovery* failures —
    the optional ``[mcp]`` extra not installed, or the server unreachable at startup —
    degrade to zero MCP tools with a stderr warning rather than failing boot: the agent
    still serves (the network-free ``--check`` boot and a not-yet-running MCP server both stay
    viable), and the operator sees why tools are absent.
    """
    import sys

    from mira.connectors.mcp_registry import load_registry
    from mira.orchestration.mcp_tools import load_mcp_tools

    registry = load_registry(profile_endpoint=profile.mcp_endpoint)
    if not registry:
        return []
    try:
        return load_mcp_tools(registry)
    except Exception as exc:  # noqa: BLE001 — degrade to no-MCP rather than fail boot
        names = ", ".join(spec.name for spec in registry)
        print(
            f"mira: MCP tool discovery failed for [{names}] ({type(exc).__name__}: {exc}); "
            "continuing with no MCP tools",
            file=sys.stderr,
        )
        return []


def _registry_with_advisor(
    mcp_tools: list[Any],
    registry: AgentCardRegistry | None,
) -> AgentCardRegistry | None:
    """Register the advisor specialist when discovery yielded ``vantage.*`` tools.

    Best-effort (matching :func:`_discover_mcp_tools`'s degrade contract): no
    vantage tools, or a bridging/registration failure, leaves the registry
    exactly as passed in — boot proceeds, /turn keeps its existing routing.
    With vantage tools and no base registry, a fresh registry is created so the
    advisor is routable even without the demo domains.
    """
    import sys

    vantage = [
        tool
        for tool in mcp_tools
        if str(getattr(tool, "name", "") or "").startswith("vantage.")
    ]
    if not vantage:
        return registry
    try:
        from mira.orchestration.specialists.demo import build_live_registry

        return build_live_registry(vantage, base=registry)
    except Exception as exc:  # noqa: BLE001 — degrade to no-advisor rather than fail boot
        print(
            f"mira: advisor registration failed ({type(exc).__name__}: {exc}); "
            "continuing without the advisor domain",
            file=sys.stderr,
        )
        return registry


def _registry_with_tier_escalation(
    registry: AgentCardRegistry | None,
    profile: Profile,
) -> AgentCardRegistry | None:
    """Wrap registered specialists in the model-tier escalating decorator (ADR-052).

    Double-flagged: requires ``MODEL_ROUTES`` (tier routing configured) and the
    ``tier_escalation`` profile flag (``ENABLE_TIER_ESCALATION`` per ADR-047).
    Absent either ⇒ the registry is returned untouched.
    """
    import os

    if registry is None:
        return None
    if not (os.environ.get("MODEL_ROUTES") or "").strip():
        return registry
    if not profile.flags.get("tier_escalation", False):
        return registry

    from mira_harness.quality import EscalationTrigger

    from mira.orchestration.tier_escalation import TierEscalatingSpecialist

    trigger = EscalationTrigger()

    def wrap(card: Any, factory: Any) -> Any:
        start_tier = card.model_hint or "light"
        return lambda: TierEscalatingSpecialist(
            factory(), trigger=trigger, start_tier=start_tier
        )

    registry.wrap_factories(wrap)
    return registry


def _gateway_from_env(
    bundle: ProviderBundle,
    registry: AgentCardRegistry | None,
) -> Gateway:
    """Build the gateway, tier-aware when ``MODEL_ROUTES`` is set (ADR-052).

    ``MODEL_ROUTES`` is a JSON list of route objects (``provider``, ``model``,
    optional ``tier``/``cost_per_1k_tokens``/``latency_ms_p50``/
    ``quota_remaining``); ``MODEL_ROUTING_STRATEGY`` optionally names the
    ranking strategy (default ``cost``). Absent/empty env ⇒ ``Gateway(bundle)``
    byte-identical to before. Malformed JSON is genuine misconfiguration and
    propagates (same contract as the MCP registry parse).
    """
    import json
    import os

    raw = (os.environ.get("MODEL_ROUTES") or "").strip()
    if not raw:
        return Gateway(bundle)

    from mira.model.routing import ModelRoute, Router, RoutingStrategy
    from mira.model.tiering import TierPolicy, classify_difficulty

    routes = [
        ModelRoute(
            provider=str(entry["provider"]),
            model=str(entry["model"]),
            cost_per_1k_tokens=float(entry.get("cost_per_1k_tokens", 0.0)),
            latency_ms_p50=float(entry.get("latency_ms_p50", 0.0)),
            quota_remaining=entry.get("quota_remaining"),
            tier=str(entry.get("tier", "")),
        )
        for entry in json.loads(raw)
    ]
    strategy = RoutingStrategy(os.environ.get("MODEL_ROUTING_STRATEGY", "cost"))

    agent_tiers: dict[str, str] = {}
    domain_keywords: dict[str, frozenset[str]] = {}
    if registry is not None:
        for card in registry.cards():
            if card.model_hint:
                agent_tiers[card.name] = card.model_hint
            domain_keywords[card.name] = card.keywords
    policy = TierPolicy(
        agent_tiers=agent_tiers,
        classifier=lambda prompt: classify_difficulty(
            prompt, domain_keywords=domain_keywords
        ),
    )
    return Gateway(bundle, router=Router(strategy=strategy, routes=routes), tier_policy=policy)


def _registry_with_foreign(
    registry: AgentCardRegistry | None,
) -> AgentCardRegistry | None:
    """Register a subprocess foreign agent when ``FOREIGN_AGENT_CMD`` is set.

    Best-effort, mirroring :func:`_registry_with_advisor`: an empty/absent env
    var leaves the registry exactly as passed in; a wiring failure degrades to
    no-foreign rather than failing boot. With a command and no base registry, a
    fresh registry is created so the foreign agent is routable on its own.
    """
    import os
    import shlex
    import sys

    command = (os.environ.get("FOREIGN_AGENT_CMD") or "").strip()
    if not command:
        return registry
    try:
        from mira_harness.cli_adapter import CliAgentAdapter

        from mira.orchestration.foreign import ForeignSpecialist, foreign_card
        from mira.orchestration.specialist_scaffold import DomainSpec

        runner = CliAgentAdapter(shlex.split(command))
        card = foreign_card(
            runner, keywords=("delegate", "external", "partner", "foreign")
        )
        spec = DomainSpec(domain_id=card.name, tool_prefixes=card.tool_prefixes)
        resolved = registry if registry is not None else AgentCardRegistry()
        resolved.register(card, lambda: ForeignSpecialist(runner, spec))
        return resolved
    except Exception as exc:  # noqa: BLE001 — degrade to no-foreign rather than fail boot
        print(
            f"mira: foreign agent registration failed ({type(exc).__name__}: {exc}); "
            "continuing without the foreign domain",
            file=sys.stderr,
        )
        return registry


def _profile_name_or_default() -> str:
    """Profile name from env, falling back to the local default profile."""
    import os

    from mira.config.profiles import PROFILE_ENV

    return os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE


def _platform_or_default(profile: Profile) -> str:
    """``PLATFORM`` env when set, else the resolved profile's platform."""
    import os

    return os.environ.get("PLATFORM") or profile.platform
