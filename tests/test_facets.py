"""Facet specialists (technical/fundamental/growth/expectations/news/thesis) —
grounded, ticker-routed, degrade-safe."""

from __future__ import annotations

from typing import Any

from mira.orchestration.specialist_scaffold import build_specialist_subgraph
from mira.orchestration.specialists.domains import (
    EXPECTATIONS_DOMAIN,
    FUNDAMENTAL_DOMAIN,
    GROWTH_DOMAIN,
    NEWS_DOMAIN,
    TECHNICAL_DOMAIN,
    THESIS_DOMAIN,
)
from mira.orchestration.specialists.facets import (
    FACET_DOMAIN_IDS,
    facet_registry_entries,
    _infer_expectations,
    _infer_fundamental,
    _infer_growth,
    _infer_news,
    _infer_technical,
    _infer_thesis,
)

from tests.fake_vantage import fake_vantage_registered_tools


def _facet(domain, inference, calls=None, failing=()):
    return build_specialist_subgraph(
        domain, fake_vantage_registered_tools(calls=calls, failing=failing),
        query_inference=inference)


def _tech(calls=None):
    return _facet(TECHNICAL_DOMAIN, _infer_technical, calls)


def _fund(calls=None):
    return _facet(FUNDAMENTAL_DOMAIN, _infer_fundamental, calls)


def _news(calls=None):
    return _facet(NEWS_DOMAIN, _infer_news, calls)


# ------------------------------------------------------------ technical facet

def test_technical_calls_analysis_and_bars_with_symbol():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _tech(calls).invoke("analyze PLTR", thread_id="t")
    assert ("vantage.analysis", {"symbol": "PLTR"}) in calls
    assert ("vantage.bars", {"symbol": "PLTR"}) in calls
    assert result.answer["facet"] == "technical"
    # grounded: carries the analysis decision + levels
    assert result.answer["analysis"]["decisions"][0]["symbol"] == "BBAI"
    assert "support" in result.answer["levels"]["levels"]


# ------------------------------------------------------------ fundamental facet

def test_fundamental_calls_fundamentals_with_symbol():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _fund(calls).invoke("analyze PLTR", thread_id="f")
    assert ("vantage.fundamentals", {"symbol": "PLTR"}) in calls
    assert result.answer["facet"] == "fundamental"
    assert result.answer["fundamentals"]["fundamentals"]["pe"] == 210.5


# ------------------------------------------------------------ growth facet

def test_growth_calls_growth_with_symbol():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _facet(GROWTH_DOMAIN, _infer_growth, calls).invoke(
        "analyze PLTR", thread_id="g")
    assert ("vantage.growth", {"symbol": "PLTR"}) in calls
    assert result.answer["facet"] == "growth"
    grown = result.answer["growth"]["growth"]
    assert grown["rule_of_40"] == 65.0
    assert grown["rule_of_40_basis"] == "yoy_growth_plus_fcf_margin"


# ------------------------------------------------------------ expectations facet

def test_expectations_calls_expectations_with_symbol():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _facet(EXPECTATIONS_DOMAIN, _infer_expectations, calls).invoke(
        "analyze PLTR", thread_id="e")
    assert ("vantage.expectations", {"symbol": "PLTR"}) in calls
    assert result.answer["facet"] == "expectations"
    exp = result.answer["expectations"]
    assert exp["implied"]["fcf_growth_10y"] == 0.42
    assert exp["assumptions"]["model"] == "two_stage_fcf_reverse_dcf"


# ------------------------------------------------------------ news + earnings facet

def test_news_calls_news_and_earnings_with_symbol():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _news(calls).invoke("analyze PLTR", thread_id="n")
    assert ("vantage.news", {"symbol": "PLTR"}) in calls
    assert ("vantage.earnings", {"symbol": "PLTR"}) in calls
    assert result.answer["facet"] == "news"
    news = result.answer["news"]["news"]
    assert news["sentiment"]["band"] == "positive"
    assert news["sentiment"]["estimated"] is True
    earnings = result.answer["earnings"]["earnings"]
    assert earnings["days_until"] == 5
    assert earnings["future_date_known"] is True


def test_news_survives_earnings_only_failure():
    result = _facet(NEWS_DOMAIN, _infer_news,
                    failing={"vantage.earnings"}).invoke("analyze PLTR", thread_id="n")
    assert result.error is None
    assert result.answer["news"]["news"]["sentiment"]["band"] == "positive"
    assert result.answer["earnings"]["status"] == "tool_error"


# ------------------------------------------------------------ thesis facet

def test_thesis_calls_ticker_plan_with_symbol():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _facet(THESIS_DOMAIN, _infer_thesis, calls).invoke(
        "analyze PLTR", thread_id="p")
    assert ("vantage.ticker_plan", {"symbol": "PLTR"}) in calls
    assert result.answer["facet"] == "thesis"
    plan = result.answer["plan"]
    assert plan["has_plan"] is True
    assert plan["plan"]["target"] == 180.0
    assert plan["plan"]["stop"] == 95.0


# ------------------------------------------------------------ degrade contract

def test_facet_tool_failure_degrades_to_structured_observation():
    # vantage.news failing -> the news facet still returns, with a tool_error obs.
    result = _facet(NEWS_DOMAIN, _infer_news,
                    failing={"vantage.news"}).invoke("analyze PLTR", thread_id="n")
    assert result.error is None  # never crashes the graph
    assert result.answer["news"]["status"] == "tool_error"


# ------------------------------------------------------------ registry entries

def test_facet_registry_entries_register_all_six():
    from mira.orchestration.agent_cards import AgentCardRegistry

    registry = AgentCardRegistry()
    for card, factory in facet_registry_entries(fake_vantage_registered_tools()):
        registry.register(card, factory)
    names = {c.name for c in registry.cards()}
    assert set(FACET_DOMAIN_IDS) <= names
    assert {"technical", "fundamental", "growth",
            "expectations", "news", "thesis"} == set(FACET_DOMAIN_IDS)
    # each factory resolves to a working specialist bound to its own facet
    tech = registry.resolve("technical")
    assert tech.domain_spec.domain_id == "technical"
    thesis = registry.resolve("thesis")
    assert thesis.invoke("analyze PLTR", thread_id="r").answer["facet"] == "thesis"


# ------------------------------------------------------------ ticker extraction

def test_extract_ticker_anchored_handles_one_letter_tickers():
    from mira.orchestration.specialists.facets import extract_ticker

    # the analyze fan-out query names the subject right after "analyze"
    assert extract_ticker("analyze O: what should I do about O") == "O"
    assert extract_ticker("analyze BRK.B") == "BRK.B"
    assert extract_ticker("analyze PLTR: is it overvalued?") == "PLTR"
    # free-form text stays conservative: one uppercase letter is a pronoun
    assert extract_ticker("what should I do about PLTR?") == "PLTR"
    assert extract_ticker("what should I do?") is None


def test_technical_fetches_relative_strength_and_scorecard():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _tech(calls).invoke("analyze PLTR", thread_id="t2")
    assert ("vantage.relative_strength", {"symbol": "PLTR"}) in calls
    assert ("vantage.rec_scorecard", {}) in calls
    rs = result.answer["relative_strength"]["relative_strength"]
    assert rs["idio_r_1m"] == -0.084
    rules = result.answer["scorecard"]["scorecard"]["rules"]
    assert rules[0]["hit_rate"] == 0.62


def test_thesis_payload_carries_risk_reward():
    calls: list[tuple[str, dict[str, Any]]] = []
    result = _facet(THESIS_DOMAIN, _infer_thesis, calls).invoke(
        "analyze PLTR", thread_id="p2")
    rr = result.answer["plan"]["risk_reward"]
    assert rr["rr_ratio"] == 1.67 and rr["status"] == "ok"
