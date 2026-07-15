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


def test_trade_analyst_registered_but_routing_disabled():
    """The trade_analyst card + its vantage.trade_dna tool are registered, but
    routing is intentionally OFF (empty keywords) until Mira's turn path
    synthesizes with a live model — today's specialist loop is a deterministic
    scaffold that would echo tool JSON, not prose, so trade reviews fall
    through to the direct model turn instead."""
    from mira.orchestration.specialists.demo import build_live_registry
    from mira.orchestration.specialists.trade_analyst import (
        REPRESENTATIVE_TRADE_QUERY,
    )
    from tests.test_advisor_specialist import fake_vantage_mcp_tools

    registry = build_live_registry(fake_vantage_mcp_tools())
    # the card IS registered (infrastructure ready) ...
    assert "trade_analyst" in {c.name for c in registry.cards()}
    # ... but a trade review does NOT route to it yet (falls to direct model)
    result = Supervisor(registry).invoke(REPRESENTATIVE_TRADE_QUERY,
                                         thread_id="route-trade")
    assert result.routed_domain != "trade_analyst"
