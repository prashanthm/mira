"""Multi-domain analyze flow: parallel group fan-out, degrade, cache, groups."""

from __future__ import annotations

from mira.orchestration.analyze import (
    DEFAULT_ANALYZE_DOMAINS,
    analyze_groups,
    analyze_subject,
    analyze_symbol,
    cached_analyze_provider,
    domains_for_group,
    normalize_subject,
)
from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.specialists.advisor import advisor_registry_entry
from mira.orchestration.specialists.facets import facet_registry_entries

from tests.fake_vantage import fake_vantage_registered_tools


def _full_registry(calls=None) -> AgentCardRegistry:
    """Facets first, advisor last — mirroring build_live_registry's order,
    which IS the equity group's fan-out and synthesis order."""
    tools = fake_vantage_registered_tools(calls=calls)
    registry = AgentCardRegistry()
    for card, factory in facet_registry_entries(tools):
        registry.register(card, factory)
    card, factory = advisor_registry_entry(tools)
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


# ------------------------------------------------------------ groups (D3-b)

def test_equity_group_resolves_from_cards_in_registration_order():
    registry = _full_registry()
    assert domains_for_group(registry, "equity") == list(DEFAULT_ANALYZE_DOMAINS)
    assert analyze_groups(registry) == ["equity"]


def test_results_come_back_in_registration_order():
    registry = _full_registry()
    result = analyze_symbol(registry, "PLTR").to_dict()
    assert [r["domain"] for r in result["results"]] == list(DEFAULT_ANALYZE_DOMAINS)


def test_new_group_is_pure_registration():
    """A future family (health, devops, ...) joins /analyze by registering
    cards with its analyze_group — zero pipeline edits (the D3-b contract)."""
    from mira.orchestration.agent_cards import AgentCard

    class _Stub:
        def __init__(self, domain):
            self._d = domain

        def invoke(self, query, *, thread_id, context=None, **kw):
            class _R:
                def to_dict(_self):
                    return {"domain": self._d, "answer": {"echo": query}, "error": None}
            return _R()

    registry = AgentCardRegistry()
    for name in ("sleep", "activity"):
        registry.register(
            AgentCard(name=name, description=name, analyze_group="health"),
            lambda n=name: _Stub(n))
    result = analyze_subject(registry, "last month", group="health").to_dict()
    assert [r["domain"] for r in result["results"]] == ["sleep", "activity"]
    assert "last month" in result["query"]


def test_subject_validation_is_group_scoped():
    # equity subjects are tickers…
    assert normalize_subject("pltr", "equity") == "PLTR"
    assert normalize_subject("not a ticker", "equity") is None
    # …but an unknown group accepts any non-blank subject verbatim
    assert normalize_subject("sleep last month", "health") == "sleep last month"
    assert normalize_subject("   ", "health") is None


def test_cached_provider_validates_by_group():
    registry = AgentCardRegistry()
    provider = cached_analyze_provider(registry, group="health")
    assert provider("") is None  # blank still rejected
    out = provider("sleep")  # non-ticker subject is fine for a non-equity group
    assert out is not None and out["results"] == []


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
