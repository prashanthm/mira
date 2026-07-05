"""Tests for the advisor domain specialist (ADR-014 Phase V3, offline fakes).

The advisor is the first MCP-backed remote-tool specialist: these tests bind it
to the fake ``vantage.*`` tools (realistic engine result shapes, no network)
and exercise intent routing, grounded end-to-end answers, cross-domain
isolation, and the tool-error degrade contract.
"""

from __future__ import annotations

import json
from typing import Any

from mira.orchestration.agent_cards import AgentCard, AgentCardRegistry
from mira.orchestration.reasoning import ReasoningLoop
from mira.orchestration.specialist_scaffold import (
    SpecialistSubgraph,
    filter_tools_by_domain,
)
from mira.orchestration.specialists.advisor import (
    ADVISOR_CARD,
    REPRESENTATIVE_ADVISOR_QUERY,
    advisor_registry_entry,
    build_advisor_specialist,
)
from mira.orchestration.specialists.demo import build_live_registry
from mira.orchestration.specialists.domains import FINANCE_DOMAIN, RESEARCH_DOMAIN

from tests.fake_vantage import (
    fake_vantage_mcp_tools,
    fake_vantage_registered_tools,
)


def _specialist_with_calls() -> tuple[SpecialistSubgraph, list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    specialist = build_advisor_specialist(fake_vantage_registered_tools(calls=calls))
    return specialist, calls


# ── scaffold identity ────────────────────────────────────────────────────────


def test_advisor_specialist_is_reasoning_subgraph() -> None:
    specialist, _ = _specialist_with_calls()
    assert isinstance(specialist, SpecialistSubgraph)
    assert isinstance(specialist.reasoning_loop, ReasoningLoop)
    assert specialist.domain_spec.domain_id == "advisor"
    assert specialist.domain_spec.tool_prefixes == frozenset({"vantage."})


# ── query inference hits each tool ───────────────────────────────────────────


def test_wash_phrasing_dispatches_wash_status_with_symbol() -> None:
    specialist, calls = _specialist_with_calls()
    result = specialist.invoke(REPRESENTATIVE_ADVISOR_QUERY, thread_id="route-wash")

    assert ("vantage.wash_status", {"symbol": "VOO"}) in calls
    assert result.answer["wash"]["VOO"]["blocked"] is True


def test_tlh_phrasing_dispatches_tlh_candidates() -> None:
    specialist, calls = _specialist_with_calls()
    result = specialist.invoke(
        "Which lots are tax-loss-harvest candidates?", thread_id="route-tlh"
    )

    assert calls and calls[0][0] == "vantage.tlh_candidates"
    statuses = {c["status"] for c in result.answer["candidates"]}
    assert statuses == {"clear", "blocked"}


def test_allocation_phrasing_dispatches_allocation() -> None:
    specialist, calls = _specialist_with_calls()
    result = specialist.invoke(
        "How far has my allocation drifted from target?", thread_id="route-alloc"
    )

    assert calls and calls[0][0] == "vantage.allocation"
    assert result.answer["by_class"]["usEquity"]["pct"] == 60.0


def test_holdings_phrasing_dispatches_positions() -> None:
    specialist, calls = _specialist_with_calls()
    result = specialist.invoke("What are my current holdings?", thread_id="route-pos")

    assert calls and calls[0][0] == "vantage.positions"
    assert result.answer["positions"][0]["symbol"] == "VOO"


def test_unrelated_query_falls_through_to_noop_without_tool_calls() -> None:
    specialist, calls = _specialist_with_calls()
    result = specialist.invoke("what is the weather today?", thread_id="route-noop")

    assert calls == []
    assert result.answer["status"] == "noop"


# ── representative query end-to-end ──────────────────────────────────────────


def test_representative_query_returns_grounded_supervisor_contract() -> None:
    specialist, _ = _specialist_with_calls()
    result = specialist.invoke(REPRESENTATIVE_ADVISOR_QUERY, thread_id="advisor-e2e")

    assert result.domain == "advisor"
    assert result.error is None
    assert result.plan_steps
    # Grounded: the answer repeats only engine numbers and carries provenance.
    assert result.answer["provenance"]["source_type"] == "vantage"
    assert result.answer["provenance"]["source_id"].endswith("#wash_status")
    assert result.answer["wash"]["VOO"]["clears_on_date"] == "2025-08-01"
    assert json.dumps(result.to_dict())  # stays supervisor-serializable


# ── cross-domain isolation ───────────────────────────────────────────────────


def test_vantage_tools_are_not_visible_to_other_domains() -> None:
    tools = fake_vantage_registered_tools()
    assert filter_tools_by_domain(tools, RESEARCH_DOMAIN) == []
    assert filter_tools_by_domain(tools, FINANCE_DOMAIN) == []


def test_advisor_cannot_call_docs_or_ledger_tools() -> None:
    specialist, calls = _specialist_with_calls()

    docs = specialist.invoke(':tool:docs.search:{"query": "middleware"}', thread_id="iso-docs")
    assert docs.error and "not allowed" in docs.error

    ledger = specialist.invoke(':tool:ledger.query:{"category": "travel"}', thread_id="iso-led")
    assert ledger.error and "not allowed" in ledger.error

    assert calls == []  # nothing was dispatched fail-open


# ── tool-error degradation ───────────────────────────────────────────────────


def test_remote_failure_degrades_to_structured_tool_error_not_crash() -> None:
    tools = fake_vantage_registered_tools(failing={"vantage.wash_status"})
    specialist = build_advisor_specialist(tools)

    result = specialist.invoke(REPRESENTATIVE_ADVISOR_QUERY, thread_id="degrade")

    # Fail-degraded: the graph completes; the failure is a structured,
    # caveat-able answer the insights layer can turn into a caveats entry.
    assert result.error is None
    assert result.answer["status"] == "tool_error"
    assert result.answer["tool"] == "vantage.wash_status"
    assert "server gone" in result.answer["detail"]


# ── card, registry entry, and live-registry wiring ───────────────────────────


def test_advisor_card_routes_portfolio_phrasing() -> None:
    registry = AgentCardRegistry()
    card, factory = advisor_registry_entry(fake_vantage_registered_tools())
    registry.register(card, factory)

    assert card is ADVISOR_CARD
    matched = registry.match(REPRESENTATIVE_ADVISOR_QUERY)
    assert matched is not None and matched.name == "advisor"
    assert registry.match("What is my portfolio allocation drift?").name == "advisor"
    assert registry.resolve("advisor").domain_spec.domain_id == "advisor"


def test_build_live_registry_adds_advisor_alongside_base() -> None:
    base = AgentCardRegistry()
    stand_in = AgentCard(name="research", description="demo", keywords=frozenset({"handbook"}))
    base.register(stand_in, lambda: None)  # type: ignore[arg-type,return-value]

    registry = build_live_registry(fake_vantage_mcp_tools(), base=base)

    assert registry is base
    assert {card.name for card in registry.cards()} == {"research", "advisor"}
    specialist = registry.resolve("advisor")
    result = specialist.invoke(REPRESENTATIVE_ADVISOR_QUERY, thread_id="live")
    assert result.answer["provenance"]["source_type"] == "vantage"


def test_build_live_registry_without_vantage_tools_keeps_base_unchanged() -> None:
    base = AgentCardRegistry()
    registry = build_live_registry([], base=base)
    assert registry is base
    assert registry.cards() == ()
