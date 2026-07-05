"""Finance domain specialist (ADR-014 second worker).

The second instantiation of the shared specialist-subgraph scaffold — no new
LangGraph wiring — proving the extension seam: a new domain is a
:class:`~mira.orchestration.specialist_scaffold.DomainSpec`, a tool allow-list,
and an optional per-domain ``query_inference`` hook over the ledger connector's
MCP tool surface (``ledger.categories``, ``ledger.query``).
"""

from __future__ import annotations

import re
from typing import Any

from mira.orchestration.reasoning import ReasoningBudget
from mira.orchestration.specialist_scaffold import (
    RegisteredTool,
    SpecialistSubgraph,
    build_specialist_subgraph,
)
from mira.orchestration.specialists.domains import FINANCE_DOMAIN

REPRESENTATIVE_FINANCE_QUERY = (
    "What was the total travel spend for 2026-03?"
)


def _infer_ledger_query(
    action: str,
    registry: dict[str, RegisteredTool],
) -> dict[str, Any] | None:
    """Pragmatic query inference for the representative spend question.

    Dispatches ``ledger.query`` when the action names the representative period
    and category; otherwise falls through to the scaffold's structured noop.
    """
    tool = registry.get("ledger.query")
    if tool is None:
        return None
    if "2026-03" not in action:
        return None
    if not re.search(r"travel", action, re.I):
        return None
    return tool.handler({"category": "travel", "period": "2026-03"})


def build_finance_specialist(
    tools: list[RegisteredTool],
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """Return the finance specialist subgraph scoped to ledger MCP tools."""
    return build_specialist_subgraph(
        FINANCE_DOMAIN,
        tools,
        budget=budget,
        query_inference=_infer_ledger_query,
    )
