"""Facet specialists for the multi-facet analysis graph (ADR-014 follow-on).

The advisor answers *position/tax* questions. These three answer the other
facets of "what should I do about SYM?", each grounded in ONE Vantage tool:

  * **technical** → ``vantage.analysis`` (the nightly decision journal: trend,
    momentum, support/resistance, conviction, which rule fired) + ``vantage.bars``
    (levels) — the market/technical read.
  * **fundamental** → ``vantage.fundamentals`` (valuation context: P/E, target,
    52w range, market cap).
  * **news** → ``vantage.news`` (recent aggregated headlines + sentiment lean).

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
    FUNDAMENTAL_DOMAIN,
    NEWS_DOMAIN,
    TECHNICAL_DOMAIN,
)

# Ticker extraction — same convention as the advisor (2-6 uppercase letters).
_TICKER = re.compile(r"\b[A-Z]{2,6}\b")


def _symbol(action: str) -> dict[str, Any]:
    match = _TICKER.search(action)
    return {"symbol": match.group(0)} if match else {}


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
)


def _infer_technical(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
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
)


def _infer_fundamental(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    result = _call(registry, "vantage.fundamentals", _symbol(action))
    if result is None:
        return None
    return {"facet": "fundamental", "fundamentals": result}


# ------------------------------------------------------------ news

NEWS_CARD: AgentCard = card_for_domain(
    NEWS_DOMAIN,
    description=(
        "News/sentiment read for one ticker — recent aggregated headlines with a "
        "headline sentiment lean (estimated, never ground truth) — from Vantage "
        "news."
    ),
    keywords=(
        "news", "headline", "headlines", "sentiment", "story", "stories",
        "press", "coverage", "media", "catalyst",
    ),
    model_hint="light",
)


def _infer_news(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    result = _call(registry, "vantage.news", _symbol(action))
    if result is None:
        return None
    return {"facet": "news", "news": result}


# ------------------------------------------------------------ builders / registry entries

_FACETS: tuple[tuple[Any, AgentCard, Callable[[str, dict[str, RegisteredTool]], dict[str, Any] | None]], ...] = (
    (TECHNICAL_DOMAIN, TECHNICAL_CARD, _infer_technical),
    (FUNDAMENTAL_DOMAIN, FUNDAMENTAL_CARD, _infer_fundamental),
    (NEWS_DOMAIN, NEWS_CARD, _infer_news),
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


#: The facet domain ids the analyze flow fans across (order = synthesis order).
FACET_DOMAIN_IDS = (TECHNICAL_DOMAIN.domain_id, FUNDAMENTAL_DOMAIN.domain_id, NEWS_DOMAIN.domain_id)


__all__ = [
    "FACET_DOMAIN_IDS",
    "FUNDAMENTAL_CARD",
    "NEWS_CARD",
    "TECHNICAL_CARD",
    "facet_registry_entries",
]
