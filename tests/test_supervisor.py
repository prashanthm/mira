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
