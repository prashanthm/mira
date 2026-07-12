"""Facet specialists for the multi-facet analysis graph (ADR-014 follow-on).

The advisor answers *position/tax* questions. These answer the other facets of
"what should I do about SYM?", each grounded in its Vantage tool(s):

  * **technical** → ``vantage.analysis`` (the nightly decision journal: trend,
    momentum, support/resistance, conviction, which rule fired) + ``vantage.bars``
    (levels) — the market/technical read.
  * **fundamental** → ``vantage.fundamentals`` (valuation context: P/E, target,
    52w range, market cap).
  * **growth** → ``vantage.growth`` (revenue growth, margins, FCF, SBC,
    Rule of 40 — what the business is doing, not what the market pays).
  * **expectations** → ``vantage.expectations`` (reverse DCF: the growth rate
    the current price already implies, with assumptions + scenarios).
  * **news** → ``vantage.news`` + ``vantage.earnings`` (headlines + sentiment
    lean, and the earnings calendar — together the catalyst read).
  * **thesis** → ``vantage.ticker_plan`` (the operator's stored thesis/target/
    stop; synthesis weighs sell/close calls against it).

Unlike the advisor (whose inference keyword-routes among many tools), a facet
specialist is dispatched via ``fan_out`` with a uniform ``"analyze SYM"`` query,
so keyword gating would miss. Each facet therefore **unconditionally** calls its
tool with the ticker extracted from the query — the facet IS the routing. Mira
does no math: it calls the tool and returns the attributed result verbatim for
the synthesis node to weave. A missing tool / remote failure degrades to a
structured observation, never a crash (matching the advisor's contract).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from mira.orchestration.agent_cards import AgentCard, card_for_domain
from mira.orchestration.reasoning import ReasoningBudget
from mira.orchestration.specialist_scaffold import (
    RegisteredTool,
    SpecialistSubgraph,
    build_specialist_subgraph,
)
from mira.orchestration.specialists.domains import (
    EXPECTATIONS_DOMAIN,
    FUNDAMENTAL_DOMAIN,
    GROWTH_DOMAIN,
    NEWS_DOMAIN,
    TECHNICAL_DOMAIN,
    THESIS_DOMAIN,
)

# Ticker extraction. The analyze fan-out query is "analyze <SUB>[: question]",
# so an anchored match handles every ticker length — including one-letter names
# (O, F, T) that the free-form pattern must not attempt, because in
# conversational text ("what should I do…") one uppercase letter is usually a
# pronoun, not a ticker. Free-form fallback stays 2-6 letters for that reason.
_ANALYZE_SUBJECT = re.compile(r"\banalyze\s+([A-Z][A-Z.]{0,5})\b")
_TICKER = re.compile(r"\b[A-Z]{2,6}\b")


def extract_ticker(action: str) -> str | None:
    """The ticker an action names: anchored ``analyze <SUB>`` first, then the
    free-form 2-6 letter convention (shared with the advisor)."""
    anchored = _ANALYZE_SUBJECT.search(action)
    if anchored:
        return anchored.group(1)
    match = _TICKER.search(action)
    return match.group(0) if match else None


def _symbol(action: str) -> dict[str, Any]:
    ticker = extract_ticker(action)
    return {"symbol": ticker} if ticker else {}


def _call(registry: dict[str, RegisteredTool], name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Call one allow-listed tool, degrading a failure to a structured observation.

    Returns None only when the tool isn't in the registry (so the scaffold falls
    through to its noop); a handler exception becomes ``{"status":"tool_error"}``.
    """
    tool = registry.get(name)
    if tool is None:
        return None
    try:
        result = tool.handler(payload)
    except PermissionError:
        raise  # fail-closed on authorization failures
    except Exception as exc:  # noqa: BLE001 — fail-degraded, never crash the graph
        return {"status": "tool_error", "tool": name, "detail": str(exc)}
    return result if isinstance(result, dict) else {"result": result}


# ------------------------------------------------------------ technical

TECHNICAL_CARD: AgentCard = card_for_domain(
    TECHNICAL_DOMAIN,
    description=(
        "Technical/market read for one ticker — trend, momentum, support/"
        "resistance, conviction, and which rule fired — grounded in the Vantage "
        "decision journal and computed levels (Mira does no math)."
    ),
    keywords=(
        "technical", "market", "trend", "momentum", "support", "resistance",
        "level", "levels", "breakout", "chart", "analysis", "signal",
    ),
    model_hint="light",
    analyze_group="equity",
    synthesis_hint=(
        "Rule-based timing signal — name the rule and weigh it by its "
        "scorecard hit rate (a ~50% rule is a coin flip). Attribute the move "
        "first: idio_r_1m vs the sector/market returns says whether the NAME "
        "is moving or its factor is."
    ),
)


def _infer_technical(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """Signal + its context: the journal decision, levels, the factor
    decomposition (is the NAME moving or its sector?), and the rules' own
    track record (scorecard) so synthesis weighs the signal by its history."""
    payload = _symbol(action)
    analysis = _call(registry, "vantage.analysis", payload)
    bars = _call(registry, "vantage.bars", payload)
    if analysis is None and bars is None:
        return None
    out: dict[str, Any] = {"facet": "technical"}
    if analysis is not None:
        out["analysis"] = analysis
    if bars is not None:
        out["levels"] = bars
    rel = _call(registry, "vantage.relative_strength", payload)
    if rel is not None:
        out["relative_strength"] = rel
    scorecard = _call(registry, "vantage.rec_scorecard", {})
    if scorecard is not None:
        out["scorecard"] = scorecard
    return out


# ------------------------------------------------------------ fundamental

FUNDAMENTAL_CARD: AgentCard = card_for_domain(
    FUNDAMENTAL_DOMAIN,
    description=(
        "Fundamental/valuation read for one ticker — P/E, forward P/E, analyst "
        "target, 52-week range, market cap, dividend, beta — from Vantage "
        "fundamentals (nulls for ETFs; never fabricated)."
    ),
    keywords=(
        "fundamental", "fundamentals", "valuation", "value", "pe", "p/e",
        "earnings", "target", "dividend", "beta", "market-cap", "overvalued",
        "undervalued",
    ),
    model_hint="light",
    analyze_group="equity",
)


def _infer_fundamental(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    result = _call(registry, "vantage.fundamentals", _symbol(action))
    if result is None:
        return None
    return {"facet": "fundamental", "fundamentals": result}


# ------------------------------------------------------------ news + earnings catalyst

NEWS_CARD: AgentCard = card_for_domain(
    NEWS_DOMAIN,
    description=(
        "News/catalyst read for one ticker — recent aggregated headlines with a "
        "headline sentiment lean (estimated, never ground truth) plus the "
        "earnings calendar (next report date, days until) — from Vantage news "
        "and earnings."
    ),
    keywords=(
        "news", "headline", "headlines", "sentiment", "story", "stories",
        "press", "coverage", "media", "catalyst", "earnings", "report",
    ),
    model_hint="light",
    analyze_group="equity",
    synthesis_hint=(
        "Sentiment is an ESTIMATED lean. CATALYST GATE: next_catalyst is the "
        "nearest dated event (earnings / ex-dividend / OpEx). If its "
        "days_until<=7, surface it and make act-now advice conditional on it; "
        "state the next earnings date when known, and future_date_known=false "
        "means the earnings date is unknown, never 'none'."
    ),
)


def _infer_news(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """News + the earnings calendar — together, the catalyst read. Either half
    failing (or missing) leaves the other intact; None only when both are."""
    payload = _symbol(action)
    news = _call(registry, "vantage.news", payload)
    earnings = _call(registry, "vantage.earnings", payload)
    if news is None and earnings is None:
        return None
    out: dict[str, Any] = {"facet": "news"}
    if news is not None:
        out["news"] = news
    if earnings is not None:
        out["earnings"] = earnings
    return out


# ------------------------------------------------------------ growth / quality

GROWTH_CARD: AgentCard = card_for_domain(
    GROWTH_DOMAIN,
    description=(
        "Growth/quality read for one ticker — revenue growth, gross/operating "
        "margin, free cash flow, stock-based compensation, Rule of 40 — from "
        "Vantage statement-derived metrics (nulls for ETFs; never fabricated)."
    ),
    keywords=(
        "growth", "revenue", "margin", "margins", "fcf", "free-cash-flow",
        "cash-flow", "sbc", "dilution", "rule-of-40", "quality", "profitability",
    ),
    model_hint="light",
    analyze_group="equity",
    synthesis_hint=(
        "Quote rule_of_40 with its basis; TTM figures lag the current quarter."
    ),
)


def _infer_growth(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    result = _call(registry, "vantage.growth", _symbol(action))
    if result is None:
        return None
    return {"facet": "growth", "growth": result}


# ------------------------------------------------------------ expectations (reverse DCF)

EXPECTATIONS_CARD: AgentCard = card_for_domain(
    EXPECTATIONS_DOMAIN,
    description=(
        "Market-implied expectations for one ticker — the reverse-DCF growth "
        "rate the current price already bakes in, with assumptions and fair-"
        "value scenarios — from Vantage expectations (model-derived context, "
        "not a price target; Mira does no math)."
    ),
    keywords=(
        "expectations", "implied", "priced-in", "priced", "dcf", "reverse-dcf",
        "fair-value", "intrinsic", "worth", "justify", "expensive", "cheap",
    ),
    model_hint="light",
    analyze_group="equity",
    synthesis_hint=(
        "Implied growth is MODEL-DERIVED: cite discount/terminal/horizon "
        "assumptions; negative_fcf = undefined (say so). Compare the bar to "
        "actual growth."
    ),
)


def _infer_expectations(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    result = _call(registry, "vantage.expectations", _symbol(action))
    if result is None:
        return None
    return {"facet": "expectations", "expectations": result}


# ------------------------------------------------------------ thesis (operator's plan)

THESIS_CARD: AgentCard = card_for_domain(
    THESIS_DOMAIN,
    description=(
        "The operator's stored thesis for one ticker — why the position is "
        "held, price target, stop/invalidation level, notes, recent journal — "
        "from Vantage ticker_plan (read-only; authored in the Vantage UI). "
        "Synthesis weighs sell/close calls against this."
    ),
    keywords=(
        "thesis", "plan", "why", "conviction", "target", "stop", "invalidation",
        "notes", "journal", "rationale",
    ),
    model_hint="light",
    analyze_group="equity",
    synthesis_hint=(
        "Weigh close/sell calls against the stored thesis and its target/stop; "
        "say BROKEN or INTACT and state the risk_reward ratio when a plan "
        "exists. No plan on file: say so, never invent one."
    ),
)


def _infer_thesis(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    result = _call(registry, "vantage.ticker_plan", _symbol(action))
    if result is None:
        return None
    return {"facet": "thesis", "plan": result}


# ------------------------------------------------------------ builders / registry entries

_FACETS: tuple[tuple[Any, AgentCard, Callable[[str, dict[str, RegisteredTool]], dict[str, Any] | None]], ...] = (
    (TECHNICAL_DOMAIN, TECHNICAL_CARD, _infer_technical),
    (FUNDAMENTAL_DOMAIN, FUNDAMENTAL_CARD, _infer_fundamental),
    (GROWTH_DOMAIN, GROWTH_CARD, _infer_growth),
    (EXPECTATIONS_DOMAIN, EXPECTATIONS_CARD, _infer_expectations),
    (NEWS_DOMAIN, NEWS_CARD, _infer_news),
    (THESIS_DOMAIN, THESIS_CARD, _infer_thesis),
)


def _build_facet(domain, tools, inference, *, budget: ReasoningBudget | None = None) -> SpecialistSubgraph:
    return build_specialist_subgraph(domain, tools, budget=budget, query_inference=inference)


def facet_registry_entries(
    tools: Sequence[RegisteredTool],
) -> list[tuple[AgentCard, Callable[[], SpecialistSubgraph]]]:
    """Card + lazy-factory pairs for every facet, ready for ``registry.register``.

    Each factory closes over the (bound) tool list and its facet's domain +
    inference, mirroring ``advisor_registry_entry``.
    """
    bound = list(tools)
    entries: list[tuple[AgentCard, Callable[[], SpecialistSubgraph]]] = []
    for domain, card, inference in _FACETS:
        # Bind loop vars by default-arg capture so each factory keeps its own facet.
        entries.append(
            (card, lambda d=domain, inf=inference: _build_facet(d, bound, inf))
        )
    return entries


#: The facet domain ids the analyze flow fans across (order = synthesis order;
#: thesis last so it frames the net takeaway right before the advisor).
FACET_DOMAIN_IDS = tuple(domain.domain_id for domain, _, _ in _FACETS)


__all__ = [
    "EXPECTATIONS_CARD",
    "FACET_DOMAIN_IDS",
    "FUNDAMENTAL_CARD",
    "GROWTH_CARD",
    "NEWS_CARD",
    "TECHNICAL_CARD",
    "THESIS_CARD",
    "facet_registry_entries",
]
