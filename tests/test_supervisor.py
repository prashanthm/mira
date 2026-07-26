"""Tests for the supervisor routing graph (ADR-014)."""

from __future__ import annotations

import json
from pathlib import Path

from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.specialists.finance import REPRESENTATIVE_FINANCE_QUERY
from mira.orchestration.specialists.research import REPRESENTATIVE_RESEARCH_QUERY
from mira.orchestration.supervisor import Supervisor, SupervisorResult

FIXTURES = Path(__file__).parent / "fixtures"


def _supervisor() -> Supervisor:
    registry = build_demo_registry(
        str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv")
    )
    return Supervisor(registry)


def test_routes_research_query_to_research_specialist():
    result = _supervisor().invoke(REPRESENTATIVE_RESEARCH_QUERY, thread_id="route-r")
    assert result.routed_domain == "research"
    assert result.results[0]["domain"] == "research"
    assert result.results[0]["answer"]["anchor"] == "middleware-ordering"
    assert "[research]" in result.synthesis


def test_routes_finance_query_to_finance_specialist():
    result = _supervisor().invoke(REPRESENTATIVE_FINANCE_QUERY, thread_id="route-f")
    assert result.routed_domain == "finance"
    assert result.results[0]["answer"]["total"] == 1336.40
    assert result.results[0]["answer"]["currency"] == "USD"


def test_unmatched_query_falls_back_to_general():
    result = _supervisor().invoke("completely unrelated question", thread_id="route-g")
    assert result.routed_domain is None
    assert result.results == []
    assert result.synthesis.startswith("[general] no specialist matched")


def test_supervisor_result_contract_serializes():
    result = _supervisor().invoke(REPRESENTATIVE_RESEARCH_QUERY, thread_id="contract")
    assert isinstance(result, SupervisorResult)
    payload = result.to_dict()
    assert json.dumps(payload)
    assert payload["routed_domain"] == "research"
    assert payload["results"][0]["plan_steps"]


def test_specialist_errors_stay_visible_in_synthesis():
    supervisor = _supervisor()
    # Explicit cross-domain tool call: research specialist may not touch ledger.*
    result = supervisor.invoke(
        "middleware handbook docs :tool:ledger.query:",
        thread_id="err",
    )
    assert result.routed_domain == "research"
    assert result.results[0]["error"]
    assert "error" in result.synthesis


def test_fan_out_dispatches_to_named_domains():
    supervisor = _supervisor()
    result = supervisor.fan_out(
        REPRESENTATIVE_RESEARCH_QUERY, ["research", "finance"], thread_id="fan"
    )
    assert [r["domain"] for r in result.results] == ["research", "finance"]
    assert "[research]" in result.synthesis
    assert "[finance]" in result.synthesis


def test_routing_is_discovery_driven_not_hardcoded():
    # A registry without finance must still route research and fall back cleanly.
    from mira.orchestration.agent_cards import AgentCardRegistry
    from mira.orchestration.specialists.demo import RESEARCH_CARD, docs_registered_tools
    from mira.orchestration.specialists.research import build_research_specialist

    registry = AgentCardRegistry()
    registry.register(
        RESEARCH_CARD,
        lambda: build_research_specialist(
            docs_registered_tools(str(FIXTURES / "handbook.md"))
        ),
    )
    supervisor = Supervisor(registry)
    assert supervisor.invoke(REPRESENTATIVE_RESEARCH_QUERY, thread_id="d1").routed_domain == "research"
    assert supervisor.invoke(REPRESENTATIVE_FINANCE_QUERY, thread_id="d2").routed_domain is None


def test_routes_trade_review_to_trade_analyst():
    """A trade-review prompt routes to the dedicated trade_analyst (Option A:
    the supervisor synthesizes routed answers with the model, so routing is
    live). It must NOT be hijacked by the equity facets."""
    from mira.orchestration.specialists.demo import build_live_registry
    from mira.orchestration.specialists.trade_analyst import (
        REPRESENTATIVE_TRADE_QUERY,
    )
    from tests.test_advisor_specialist import fake_vantage_mcp_tools

    registry = build_live_registry(fake_vantage_mcp_tools())
    assert "trade_analyst" in {c.name for c in registry.cards()}
    result = Supervisor(registry).invoke(REPRESENTATIVE_TRADE_QUERY,
                                         thread_id="route-trade")
    assert result.routed_domain == "trade_analyst"


def test_synthesize_uses_the_model_when_present():
    """Option A: with an LLM, the synthesize node writes prose from the
    specialist result + the card's synthesis_hint — not the deterministic
    [domain]{json} echo. Without an LLM, the deterministic path is unchanged."""
    class _Echo:
        def complete(self, prompt, *, model=None):
            return f"MODEL_SYNTHESIS<<{prompt}>>"     # echoes the whole prompt

    registry = build_demo_registry(
        str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv"))

    # with a model → prose synthesis (the fake wraps the prompt)
    withllm = Supervisor(registry, llm=_Echo()).invoke(
        REPRESENTATIVE_RESEARCH_QUERY, thread_id="synth-llm")
    assert withllm.synthesis.startswith("MODEL_SYNTHESIS")
    # the model saw the specialist payload (the prompt carries the [research]
    # result) — synthesis is grounded, not free-form
    assert "[research]" in withllm.synthesis
    assert "Middleware Ordering" in withllm.synthesis

    # without a model → the deterministic digest, unchanged
    plain = Supervisor(registry).invoke(
        REPRESENTATIVE_RESEARCH_QUERY, thread_id="synth-plain")
    assert plain.synthesis.startswith("[research]")


def test_synthesis_falls_back_when_the_model_errors():
    """A model failure must degrade to the deterministic digest, never blank
    the answer."""
    class _Boom:
        def complete(self, prompt, *, model=None):
            raise RuntimeError("model down")

    registry = build_demo_registry(
        str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv"))
    result = Supervisor(registry, llm=_Boom()).invoke(
        REPRESENTATIVE_RESEARCH_QUERY, thread_id="synth-boom")
    assert result.synthesis.startswith("[research]")   # deterministic fallback


def test_classify_with_model_returns_valid_card_or_none():
    """The LLM route fallback returns an EXACT card name or None — never a
    guess; a reply that isn't a card name (or a model error) → None."""
    from mira.orchestration.supervisor import classify_with_model
    from mira.orchestration.agent_cards import AgentCard
    cards = [AgentCard(name="advisor", description="portfolio + tax questions",
                       keywords=frozenset({"portfolio"})),
             AgentCard(name="forecast_analyst", description="intraday price forecast",
                       keywords=frozenset({"forecast"}))]

    class _Pick:
        def __init__(self, reply): self.reply = reply
        def complete(self, prompt, *, model=None): return self.reply
    assert classify_with_model(_Pick("advisor"), "am I over-allocated?", cards) == "advisor"
    assert classify_with_model(_Pick("forecast_analyst\n"), "where's price headed?", cards) == "forecast_analyst"
    assert classify_with_model(_Pick("NONE"), "what's the weather?", cards) is None
    assert classify_with_model(_Pick("banana"), "gibberish", cards) is None  # not a card

    class _Boom:
        def complete(self, prompt, *, model=None): raise RuntimeError("down")
    assert classify_with_model(_Boom(), "anything", cards) is None  # never raises


def test_classify_node_uses_llm_fallback_only_on_keyword_miss():
    """Keyword hit → deterministic route (no model call). Keyword miss + llm →
    the model route. Keyword miss + no llm → general path (unchanged)."""
    registry = build_demo_registry(
        str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv"))

    class _RouteTo:
        # replies with the domain NAME to the classify prompt (contains
        # "DOMAINS:"), and echoes for the synthesis call — mirroring the real
        # two-call flow (route, then synthesize).
        def __init__(self, name): self.name = name; self.calls = 0
        def complete(self, prompt, *, model=None):
            self.calls += 1
            return self.name if "DOMAINS:" in prompt else f"MODEL_SYNTHESIS<<{prompt}>>"
    # a query with NO keyword hit routes via the model to the named domain
    # (>=1 model call: classify + synthesis; outcome is what matters — it
    # reached the research specialist despite zero keyword hits)
    picker = _RouteTo("research")
    res = Supervisor(registry, llm=picker).invoke(
        "tell me something obscure and unmatched xyzzy", thread_id="route-llm")
    assert res.routed_domain == "research"
    assert res.synthesis.startswith("MODEL_SYNTHESIS")   # synthesized, not general
    assert "[research]" in res.synthesis                 # grounded in the specialist result
    assert picker.calls >= 2                             # classify + synthesize
    # a keyword miss with NO llm → general path, unchanged (no routing guess)
    plain = Supervisor(registry).invoke(
        "tell me something obscure and unmatched xyzzy", thread_id="route-none")
    assert plain.routed_domain in ("", None)
    assert plain.synthesis.startswith("[general]")
