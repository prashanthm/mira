"""Research domain specialist (ADR-014 first worker).

Demonstrates the specialist-subgraph scaffold over the docs connector's MCP tool
surface (``docs.sections``, ``docs.search``): per-domain tool allow-listing,
namespaced checkpointer threads, and a supervisor-consumable result — with a
pragmatic per-domain ``query_inference`` hook for the representative question.
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
from mira.orchestration.specialists.domains import RESEARCH_DOMAIN

REPRESENTATIVE_RESEARCH_QUERY = (
    "What does the engineering handbook say about middleware ordering?"
)


def _infer_docs_search(
    action: str,
    registry: dict[str, RegisteredTool],
) -> dict[str, Any] | None:
    """Pragmatic query inference for the representative handbook question.

    Dispatches ``docs.search`` when the action names the middleware topic;
    otherwise falls through to the scaffold's structured noop.
    """
    tool = registry.get("docs.search")
    if tool is None:
        return None
    if not re.search(r"middleware", action, re.I):
        return None
    return tool.handler({"query": "middleware"})


def build_research_specialist(
    tools: list[RegisteredTool],
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """Return the research specialist subgraph scoped to docs MCP tools."""
    return build_specialist_subgraph(
        RESEARCH_DOMAIN,
        tools,
        budget=budget,
        query_inference=_infer_docs_search,
    )
