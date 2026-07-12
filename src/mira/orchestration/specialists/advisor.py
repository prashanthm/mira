"""Advisor domain specialist (ADR-014 Phase V3 — first MCP-backed remote domain).

The third instantiation of the shared specialist-subgraph scaffold, and the
first whose tools are *remote*: the allow-list covers the ``vantage.`` surface
the Vantage MCP server (:8640/mcp) exposes — positions, allocation, wash
status, TLH candidates, lots, quotes — bridged into
:class:`~mira.orchestration.specialist_scaffold.RegisteredTool` by
:func:`mira.orchestration.mcp_bridge.registered_tools_from_mcp`.

Mira performs **no portfolio math**: every number in an advisor answer comes
from a Vantage tool result, each carrying a provenance block
``{"source_type": "vantage", "source_id": "<data-dir>#<dataset>"}``. The
specialist only calls tools and reshapes attributed answers.

Query inference is deterministic regex intent mapping (same pattern as the
finance/research demo specialists): wash/harvest phrasing dispatches
``vantage.wash_status``, TLH/candidate phrasing ``vantage.tlh_candidates``,
allocation/drift phrasing ``vantage.allocation``, holdings/positions phrasing
``vantage.positions``. Anything else falls through to the scaffold's
structured noop. A remote tool failing inside the inference path degrades to
the same structured ``{"status": "tool_error"}`` observation the scaffold's
explicit-call channel produces — a flaky server never crashes the graph.
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
from mira.orchestration.specialists.domains import ADVISOR_DOMAIN

REPRESENTATIVE_ADVISOR_QUERY = "Am I wash-safe to harvest VOO?"

ADVISOR_CARD: AgentCard = card_for_domain(
    ADVISOR_DOMAIN,
    model_hint="deep",
    analyze_group="equity",
    synthesis_hint=(
        "Cover wash-sale status, loss/credit math, and position size context "
        "(weight_pct / x_median_position) before endorsing an action."
    ),
    description=(
        "Answers portfolio questions (holdings, allocation, wash-sale windows, "
        "tax-loss-harvest candidates) grounded in the read-only Vantage engine — "
        "Mira does no portfolio math."
    ),
    keywords=(
        "portfolio",
        "holdings",
        "positions",
        "wash",
        "wash-sale",
        "wash-safe",
        "harvest",
        "tlh",
        "tax",
        "tax-loss",
        "allocation",
        "drift",
        "lots",
        "lot",
        "gains",
        "losses",
        "rebalance",
        "shares",
        "quotes",
        "vantage",
        # decision-journal phrasing (routes to position_actions / analysis)
        "recommendation",
        "recommend",
        "action",
        "close",
        "book",
        "sell",
        "call",
        "covered",
        "conviction",
        "losing",
        # trade-review phrasing (routes to trade_stats — grounded lessons/edges)
        "learned",
        "learn",
        "edge",
        "edges",
        "leak",
        "leaks",
        "lesson",
        "lessons",
        "pattern",
        "patterns",
        "win-rate",
        "profit-factor",
        "roundtrip",
        "roundtrips",
        "realized",
        "closed",
        "review",
    ),
)

# Intent → (tool name, payload builder). Ordered: TLH phrasing is checked before
# the generic wash/harvest phrasing so "tax-loss-harvest candidates" reaches
# vantage.tlh_candidates rather than the wash check it also mentions.
def _wash_payload(action: str) -> dict[str, Any]:
    """Symbol payload when the action names an uppercase ticker, else all symbols."""
    from mira.orchestration.specialists.facets import extract_ticker

    ticker = extract_ticker(action)
    return {"symbol": ticker} if ticker else {}


def _symbol_payload(action: str) -> dict[str, Any]:
    """Symbol filter when the action names an uppercase ticker, else all symbols."""
    from mira.orchestration.specialists.facets import extract_ticker

    ticker = extract_ticker(action)
    return {"symbol": ticker} if ticker else {}


# Intent → (tool, payload builder), evaluated in order — first match wins.
#
# The decision-journal intents sit FIRST and are matched before the generic
# holdings/wash/tlh intents, so "any positions to close?" reaches the journal
# (vantage.analysis, which carries the CLOSE evidence + wash status) instead of
# vantage.positions, and "which calls should I sell?" / "what should I do with
# PLTR?" reach vantage.position_actions (the compact per-symbol recommendation
# view) rather than the wash check. Their patterns are deliberately specific:
#
#   * close / book (the) loss / losing / freefall            -> vantage.analysis
#     (the CLOSE_AND_BOOK_LOSS surface — full evidence incl. wash status)
#   * what/which should I ... , sell (a) call, covered call,
#     recommendation, action                                 -> vantage.position_actions
#     (compact {symbol, conviction, recommendation, action_detail})
#
# "tax-loss" / "TLH" still reaches vantage.tlh_candidates because that intent's
# pattern is checked before the generic wash intent, and the close intent below
# is scoped to "book (the) loss" / "close" phrasing, not the word "loss" alone.
_INTENTS: tuple[tuple[re.Pattern[str], str, Callable[[str], dict[str, Any]]], ...] = (
    (
        # Trade-review: "what have I learned", "what are my edges/leaks", "when do
        # I trade best", "my win rate / profit factor". Sits FIRST so the
        # reflective phrasing is not stolen by the generic close/position intents.
        # Routes to vantage.trade_stats (the notable edges/leaks + baseline the
        # advisor narrates as grounded lessons — never a small-n bucket).
        re.compile(
            r"what\s+have\s+i\s+learned|\blesson|\bedges?\b|\bleaks?\b|"
            r"when\s+do\s+i\s+trade\s+best|trade\s+best|"
            r"my\s+(trading\s+)?(edge|pattern)|win[-\s]?rate|profit[-\s]?factor|"
            r"trade\s+stats|trade\s+review|trade\s+analytics",
            re.I,
        ),
        "vantage.trade_stats",
        lambda _a: {},
    ),
    (
        # Round-trip history / realized trade record → vantage.roundtrips (the
        # labeled closed trades + win-rate/profit-factor summary). Checked before
        # the generic close/position intents so "my round trips" / "realized
        # trades" / "closed trades" reach the journal-of-record, not the analyzer.
        re.compile(
            r"round[-\s]?trips?|realized\s+(pnl|p/l|trades?|record)|"
            r"closed\s+trades?|trade\s+history|my\s+trades\b",
            re.I,
        ),
        "vantage.roundtrips",
        _symbol_payload,
    ),
    (
        re.compile(
            r"\bclose\b|book[-\s]?(the\s+)?loss|losing\s+position|freefall|"
            r"\bcut\b.*\bloss|which.*\bclose\b",
            re.I,
        ),
        "vantage.analysis",
        _symbol_payload,
    ),
    (
        re.compile(
            r"sell\s+(a\s+|which\s+|the\s+)?call|covered\s+call|"
            r"what\s+should\s+i\s+do|which.*should\s+i\s+sell|"
            r"\brecommendation\b|\brecommend\b|conviction|per[-\s]?position\s+action",
            re.I,
        ),
        "vantage.position_actions",
        _symbol_payload,
    ),
    (re.compile(r"\btlh\b|candidate|tax[-\s]?loss", re.I), "vantage.tlh_candidates", lambda _a: {}),
    (re.compile(r"wash|harvest", re.I), "vantage.wash_status", _wash_payload),
    (re.compile(r"allocation|drift|asset[-\s]?class", re.I), "vantage.allocation", lambda _a: {}),
    (re.compile(r"holding|position", re.I), "vantage.positions", lambda _a: {}),
)


def _infer_vantage_query(
    action: str,
    registry: dict[str, RegisteredTool],
) -> dict[str, Any] | None:
    """Deterministic intent mapping over the advisor's allow-listed tool registry.

    Returns the tool result to serve as the observation, or None to fall through
    to the scaffold's structured noop. Remote failures degrade to a structured
    ``tool_error`` observation (matching the scaffold's explicit-call channel)
    instead of escaping the graph; authorization failures stay fail-closed.
    """
    for pattern, tool_name, payload_for in _INTENTS:
        if not pattern.search(action):
            continue
        tool = registry.get(tool_name)
        if tool is None:
            return None
        try:
            result = tool.handler(payload_for(action))
        except PermissionError:
            raise  # fail-closed: authorization failures surface as errors
        except Exception as exc:  # noqa: BLE001 — fail-degraded, never crash the graph
            return {"status": "tool_error", "tool": tool_name, "detail": str(exc)}
        return result if isinstance(result, dict) else {"result": result}
    return None


def build_advisor_specialist(
    tools: list[RegisteredTool],
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """Return the advisor specialist subgraph scoped to the vantage.* MCP tools."""
    return build_specialist_subgraph(
        ADVISOR_DOMAIN,
        tools,
        budget=budget,
        query_inference=_infer_vantage_query,
    )


def advisor_registry_entry(
    tools: Sequence[RegisteredTool],
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory pair, ready for :meth:`AgentCardRegistry.register`."""
    bound = list(tools)
    return ADVISOR_CARD, lambda: build_advisor_specialist(bound)


__all__ = [
    "ADVISOR_CARD",
    "REPRESENTATIVE_ADVISOR_QUERY",
    "advisor_registry_entry",
    "build_advisor_specialist",
]
