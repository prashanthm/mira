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
    ),
)

# Intent → (tool name, payload builder). Ordered: TLH phrasing is checked before
# the generic wash/harvest phrasing so "tax-loss-harvest candidates" reaches
# vantage.tlh_candidates rather than the wash check it also mentions.
_TICKER = re.compile(r"\b[A-Z]{2,6}\b")


def _wash_payload(action: str) -> dict[str, Any]:
    """Symbol payload when the action names an uppercase ticker, else all symbols."""
    match = _TICKER.search(action)
    return {"symbol": match.group(0)} if match else {}


_INTENTS: tuple[tuple[re.Pattern[str], str, Callable[[str], dict[str, Any]]], ...] = (
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
