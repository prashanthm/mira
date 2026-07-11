"""Multi-facet analyze flow: fan-out across facets + advisor, degrade, cache."""

from __future__ import annotations

from mira.orchestration.analyze import (
    DEFAULT_ANALYZE_DOMAINS,
    analyze_symbol,
    cached_analyze_provider,
)
from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.specialists.advisor import advisor_registry_entry
from mira.orchestration.specialists.facets import facet_registry_entries

from tests.fake_vantage import fake_vantage_registered_tools


def _full_registry(calls=None) -> AgentCardRegistry:
    tools = fake_vantage_registered_tools(calls=calls)
    registry = AgentCardRegistry()
    card, factory = advisor_registry_entry(tools)
    registry.register(card, factory)
    for card, factory in facet_registry_entries(tools):
        registry.register(card, factory)
    return registry


def _by_domain(result_dict) -> dict:
    return {r["domain"]: r for r in result_dict["results"]}


# ------------------------------------------------------------ fan-out coverage

def test_analyze_fans_across_all_facets_and_advisor():
    registry = _full_registry()
    result = analyze_symbol(registry, "PLTR").to_dict()
    by = _by_domain(result)
    # every default domain produced an attributed result
    assert set(by) == set(DEFAULT_ANALYZE_DOMAINS)
    assert by["technical"]["answer"]["facet"] == "technical"
    assert by["fundamental"]["answer"]["facet"] == "fundamental"
    assert by["news"]["answer"]["facet"] == "news"
    # the advisor rode along (position/tax facet)
    assert by["advisor"]["answer"]  # non-empty grounded answer


def test_analyze_query_carries_symbol_uppercase():
    calls: list = []
    registry = _full_registry(calls=calls)
    analyze_symbol(registry, "pltr")  # lowercased input
    # each facet tool was called with the uppercased ticker
    assert ("vantage.fundamentals", {"symbol": "PLTR"}) in calls
    assert ("vantage.news", {"symbol": "PLTR"}) in calls


def test_analyze_folds_user_question_into_query():
    registry = _full_registry()
    result = analyze_symbol(registry, "PLTR", question="is it overvalued?").to_dict()
    assert "overvalued" in result["query"]
    assert "PLTR" in result["query"]


# ------------------------------------------------------------ degrade

def test_analyze_skips_unregistered_domains():
    # Only the news facet registered -> fan-out covers just that, no crash on the
    # missing technical/fundamental/advisor domains.
    registry = AgentCardRegistry()
    entries = {c.name: (c, f) for c, f in facet_registry_entries(fake_vantage_registered_tools())}
    card, factory = entries["news"]
    registry.register(card, factory)
    result = analyze_symbol(registry, "PLTR").to_dict()
    assert {r["domain"] for r in result["results"]} == {"news"}


def test_analyze_empty_registry_returns_wellformed_empty():
    result = analyze_symbol(AgentCardRegistry(), "PLTR").to_dict()
    assert result["results"] == []
    assert result["synthesis"] == ""


# ------------------------------------------------------------ provider + cache

def test_cached_analyze_provider_caches_and_refreshes():
    calls: list = []
    registry = _full_registry(calls=calls)
    provider = cached_analyze_provider(registry)

    first = provider("PLTR")
    n_after_first = len(calls)
    assert first is not None
    # second call served from cache -> no new tool dispatches
    provider("PLTR")
    assert len(calls) == n_after_first
    # refresh re-runs the fan-out
    provider("PLTR", refresh=True)
    assert len(calls) > n_after_first


def test_cached_analyze_provider_rejects_bad_symbol():
    provider = cached_analyze_provider(_full_registry())
    assert provider("") is None
    assert provider("not a ticker") is None


def test_cached_analyze_provider_question_is_cache_key():
    calls: list = []
    provider = cached_analyze_provider(_full_registry(calls=calls))
    provider("PLTR", "overvalued?")
    n = len(calls)
    # a different question is a distinct cache entry -> new dispatches
    provider("PLTR", "any bad news?")
    assert len(calls) > n


# ------------------------------------------------------------ LLM synthesis path


class _FakeLLM:
    def __init__(self, reply="grounded multi-facet synthesis"):
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, prompt, *, model=None):
        self.prompts.append(prompt)
        return self.reply

    def embed(self, text):
        return [0.0]


def test_analyze_with_llm_replaces_synthesis_with_prose():
    llm = _FakeLLM()
    result = analyze_symbol(_full_registry(), "PLTR", llm=llm).to_dict()
    assert result["synthesis"] == "grounded multi-facet synthesis"
    # the facets' grounded facts reached the synthesis prompt
    assert "HOLD_AND_SELL_CALL" in llm.prompts[0] or "recommendation" in llm.prompts[0]


def test_analyze_without_llm_keeps_deterministic_synthesis():
    # no llm -> the supervisor's deterministic [domain] {json} concat, not prose.
    result = analyze_symbol(_full_registry(), "PLTR").to_dict()
    assert "[technical]" in result["synthesis"]


def test_cached_analyze_provider_threads_llm():
    llm = _FakeLLM(reply="cached prose")
    provider = cached_analyze_provider(_full_registry(), llm=llm)
    out = provider("PLTR")
    assert out["synthesis"] == "cached prose"
