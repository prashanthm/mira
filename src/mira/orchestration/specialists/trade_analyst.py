"""The trade-analyst specialist — reviews ONE options trade from its full DNA.

Step 2 of Vantage's two-step trade-review flow: Vantage assembles the DATA
(price action, volume, technicals, entry/exit level correlation, forecast) and
posts it as a self-contained brief; this specialist owns the JUDGMENT.

WHY A DEDICATED CARD. The trade brief kept getting hijacked by the equity
fan-out (a "SPX ... trade" prompt matched the technical/advisor cards, which
re-fetched ticker facets and dumped raw JSON instead of reading the DNA). A
routed specialist with trade-review keywords wins the supervisor's
classification and answers directly.

NO TOOLS. Everything the analyst needs is in the prompt — the DNA is already
built. The specialist is a pure reasoning loop over the model; its domain
binds no tool prefix, so it never fans out to a facet. (News/sentiment
enrichment via the news facet is a later increment; today the analyst reasons
over the tape + broad market context the brief carries.)
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from mira.orchestration.agent_cards import AgentCard, card_for_domain
from mira.orchestration.specialist_scaffold import (
    DomainSpec,
    ReasoningBudget,
    RegisteredTool,
    SpecialistSubgraph,
    build_specialist_subgraph,
)

# The prompt carries a machine-readable ref line the inference parses to fetch
# the DNA — "TRADE_REF day=2026-07-14 trade=0 underlying=SPX".
_REF = re.compile(r"TRADE_REF\s+day=(\S+)\s+trade=(\d+)\s+underlying=(\S+)")


def _infer_trade_dna(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """Fetch the trade's DNA via vantage.trade_dna from the TRADE_REF line in
    the query. The analyst then reasons over the returned DNA — Vantage owns
    the data tool, this specialist owns the judgment."""
    m = _REF.search(action or "")
    tool = registry.get("vantage.trade_dna")
    if m is None or tool is None:
        return None
    try:
        return tool.handler({"day": m.group(1), "trade": int(m.group(2)),
                             "underlying": m.group(3)})
    except Exception:  # noqa: BLE001 — a fetch failure degrades, never crashes
        return None

TRADE_DOMAIN = DomainSpec(
    domain_id="trade_analyst",
    # binds the ONE Vantage DNA tool: the analyst fetches the trade's DNA
    # (price action / volume / technicals / level correlation) and reasons
    # over it. The specialist scaffold requires at least one tool, and this is
    # the clean shape — Vantage owns the data tool, Mira owns the judgment.
    tool_prefixes=frozenset({"vantage."}),
)

TRADE_ANALYST_CARD: AgentCard = card_for_domain(
    TRADE_DOMAIN,
    model_hint="deep",
    # deliberately NOT analyze_group="equity": this is a routed /turn
    # specialist, not a fan-out facet, so a trade review never triggers the
    # per-ticker analysis graph.
    description=(
        "Reviews ONE executed options trade from its full DNA — the price "
        "action and volume around entry and exit, the technicals at each "
        "fill, and how the entry/exit correlated to the session's forecast "
        "levels. Grades the QUALITY of the decision (bought strength vs "
        "caught a knife; sold a spike vs gave it back; respected the plan or "
        "improvised) and returns one concrete lesson."
    ),
    # The classifier scores SINGLE-WORD keyword hits (registry.match tokenizes
    # the query into a word set). These fire on a trade-review brief while
    # staying off plain equity analysis — "trade"+"grade"/"critique"/"fill"/
    # "entry"/"exit" together is a review; "analyze SPY" alone is not. Routing
    # is now live because the supervisor synthesizes with the model (Option A):
    # the analyst fetches the DNA via vantage.trade_dna, and the synthesize
    # node — guided by the hint below — writes the prose review.
    keywords=frozenset({
        "trade", "trades", "grade", "critique", "fill", "fills",
        "entry", "exit", "reentry", "review", "dna", "desk", "footprint",
    }),
    synthesis_hint=(
        "Write a tight desk review of this ONE trade from its DNA. Judge the "
        "DECISION, not the outcome — a winning trade with a sloppy entry is "
        "still sloppy. Structure it:\n"
        "1. ENTRY quality — bought strength or caught a falling knife? At a "
        "real forecast level? What did volume/VWAP say?\n"
        "2. EXIT quality — sold into a spike or gave the move back? At a level? "
        "Extended (VWAP/RSI)?\n"
        "3. Did it RESPECT THE PLAN — enter and exit at forecast levels, in "
        "line with the tape?\n"
        "4. One concrete LESSON.\n"
        "Cite the actual numbers from the DNA (points moved before/after each "
        "fill, VWAP, RSI, relative volume, distance to the level). Be direct."
    ),
)

#: A representative query so routing/eval fixtures can exercise the card.
REPRESENTATIVE_TRADE_QUERY = "Review this trade and grade the entry and exit quality."


def build_trade_analyst_specialist(
    tools: list[RegisteredTool] | None = None,
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """The trade-analyst subgraph. Binds no tools — a pure reasoning loop over
    the DNA carried in the prompt."""
    return build_specialist_subgraph(
        TRADE_DOMAIN,
        list(tools or []),
        budget=budget or ReasoningBudget(max_steps=4),
        query_inference=_infer_trade_dna,
    )


def trade_analyst_registry_entry(
    tools: Sequence[RegisteredTool] | None = None,
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory, ready for ``AgentCardRegistry.register``."""
    return TRADE_ANALYST_CARD, lambda: build_trade_analyst_specialist(list(tools or []))


__all__ = [
    "TRADE_ANALYST_CARD",
    "TRADE_DOMAIN",
    "REPRESENTATIVE_TRADE_QUERY",
    "build_trade_analyst_specialist",
    "trade_analyst_registry_entry",
]
