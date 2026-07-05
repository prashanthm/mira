"""Tests for agent cards and the discovery registry (ADR-035 slice)."""

from __future__ import annotations

import pytest

from mira.orchestration.agent_cards import (
    AgentCard,
    AgentCardRegistry,
    UnknownAgentError,
    card_for_domain,
)
from mira.orchestration.specialists.domains import FINANCE_DOMAIN, RESEARCH_DOMAIN


def _cards() -> tuple[AgentCard, AgentCard]:
    research = card_for_domain(
        RESEARCH_DOMAIN,
        description="docs specialist",
        keywords=("handbook", "middleware", "docs"),
    )
    finance = card_for_domain(
        FINANCE_DOMAIN,
        description="ledger specialist",
        keywords=("spend", "travel", "total"),
    )
    return research, finance


def test_card_for_domain_single_sources_identity():
    research, _ = _cards()
    assert research.name == "research"
    assert research.tool_prefixes == frozenset({"docs."})
    assert "middleware" in research.keywords


def test_card_to_dict_is_a2a_shaped():
    research, _ = _cards()
    payload = research.to_dict()
    assert payload["name"] == "research"
    assert payload["version"] == "1"
    assert payload["capabilities"]["tool_prefixes"] == ["docs."]
    assert "handbook" in payload["capabilities"]["keywords"]


def test_registry_registers_and_lists_cards():
    research, finance = _cards()
    registry = AgentCardRegistry()
    registry.register(research, lambda: pytest.fail("must not instantiate"))
    registry.register(finance, lambda: pytest.fail("must not instantiate"))
    assert [card.name for card in registry.cards()] == ["research", "finance"]


def test_registry_resolve_instantiates_lazily_and_caches():
    research, _ = _cards()
    registry = AgentCardRegistry()
    calls = []

    class FakeSpecialist:
        pass

    def factory():
        calls.append(1)
        return FakeSpecialist()

    registry.register(research, factory)
    assert calls == []  # lazy
    first = registry.resolve("research")
    second = registry.resolve("research")
    assert first is second
    assert calls == [1]  # cached


def test_registry_resolve_unknown_fails_closed():
    registry = AgentCardRegistry()
    with pytest.raises(UnknownAgentError):
        registry.resolve("nonexistent")


def test_match_scores_keyword_hits():
    research, finance = _cards()
    registry = AgentCardRegistry()
    registry.register(research, lambda: None)
    registry.register(finance, lambda: None)

    assert registry.match("what does the handbook say about middleware?").name == "research"
    assert registry.match("total travel spend for March").name == "finance"


def test_match_returns_none_on_zero_hits():
    research, finance = _cards()
    registry = AgentCardRegistry()
    registry.register(research, lambda: None)
    registry.register(finance, lambda: None)
    assert registry.match("completely unrelated query") is None


def test_match_ties_resolve_to_first_registered():
    a = AgentCard(name="a", description="", keywords=frozenset({"shared"}))
    b = AgentCard(name="b", description="", keywords=frozenset({"shared"}))
    registry = AgentCardRegistry()
    registry.register(a, lambda: None)
    registry.register(b, lambda: None)
    assert registry.match("a shared keyword").name == "a"
