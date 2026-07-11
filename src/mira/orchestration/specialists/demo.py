"""Demo-domain wiring: connector-backed registered tools + agent-card registry.

One place that turns the two demo connectors into supervisor-routable
specialists, shared by tests, evals, and smoke runs. Real deployments wire
tools from live MCP discovery instead; the registry contract is identical.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mira.connectors import export_tools
from mira.connectors.docs import from_file as docs_from_file
from mira.connectors.ledger import from_file as ledger_from_file
from mira.orchestration.agent_cards import AgentCard, AgentCardRegistry, card_for_domain
from mira.orchestration.specialist_scaffold import RegisteredTool
from mira.orchestration.specialists.domains import FINANCE_DOMAIN, RESEARCH_DOMAIN
from mira.orchestration.specialists.finance import build_finance_specialist
from mira.orchestration.specialists.research import build_research_specialist

RESEARCH_CARD: AgentCard = card_for_domain(
    RESEARCH_DOMAIN,
    description="Answers questions over the document corpus with citable section anchors.",
    keywords=("handbook", "docs", "document", "documentation", "section", "middleware", "architecture"),
    model_hint="light",
)

FINANCE_CARD: AgentCard = card_for_domain(
    FINANCE_DOMAIN,
    description="Answers spend questions over the transaction ledger with denominated totals.",
    keywords=("spend", "travel", "ledger", "total", "cost", "category", "budget"),
    model_hint="standard",
)


def docs_registered_tools(handbook_path: str) -> list[RegisteredTool]:
    """Bind the docs connector's MCP contracts to in-process handlers."""
    connector = docs_from_file(handbook_path)
    contracts = {tool.name: tool for tool in export_tools(connector)}

    def sections_handler(_payload: dict) -> list[dict[str, str]]:
        return [
            {"anchor": section.anchor, "title": section.title}
            for section in connector.document.sections
        ]

    def search_handler(payload: dict) -> dict:
        record = connector.query(payload)[0]
        return {
            "anchor": record.payload["anchor"],
            "title": record.payload["title"],
            "snippet": record.payload["snippet"],
            "provenance": {
                "source_type": record.provenance.source_type,
                "source_id": record.provenance.source_id,
            },
        }

    return [
        RegisteredTool(contract=contracts["docs.sections"], handler=sections_handler),
        RegisteredTool(contract=contracts["docs.search"], handler=search_handler),
    ]


def ledger_registered_tools(ledger_path: str) -> list[RegisteredTool]:
    """Bind the ledger connector's MCP contracts to in-process handlers."""
    connector = ledger_from_file(ledger_path)
    contracts = {tool.name: tool for tool in export_tools(connector)}

    def categories_handler(_payload: dict) -> list[str]:
        return list(connector.document.categories())

    def query_handler(payload: dict) -> dict:
        record = connector.query(payload)[0]
        return {
            "total": record.payload["total"],
            "currency": record.provenance.units,
            "entry_count": record.payload["entry_count"],
            "provenance": {
                "source_type": record.provenance.source_type,
                "source_id": record.provenance.source_id,
            },
        }

    return [
        RegisteredTool(contract=contracts["ledger.categories"], handler=categories_handler),
        RegisteredTool(contract=contracts["ledger.query"], handler=query_handler),
    ]


def build_demo_registry(handbook_path: str, ledger_path: str) -> AgentCardRegistry:
    """Registry with both demo specialists, ready for a :class:`Supervisor`."""
    registry = AgentCardRegistry()
    registry.register(
        RESEARCH_CARD,
        lambda: build_research_specialist(docs_registered_tools(handbook_path)),
    )
    registry.register(
        FINANCE_CARD,
        lambda: build_finance_specialist(ledger_registered_tools(ledger_path)),
    )
    return registry


def build_live_registry(
    mcp_tools: Sequence[Any],
    *,
    base: AgentCardRegistry | None = None,
) -> AgentCardRegistry:
    """Extend ``base`` (or a fresh registry) with MCP-backed live specialists.

    Tools discovered with the ``vantage.`` namespace are bridged
    (:func:`~mira.orchestration.mcp_bridge.registered_tools_from_mcp`) and
    registered as the advisor specialist (ADR-014 Phase V3) alongside whatever
    ``base`` already holds — typically the research/finance demo domains, which
    keep working unchanged when the MCP server is absent (no vantage tools ⇒
    ``base`` is returned as-is).
    """
    from mira.orchestration.mcp_bridge import registered_tools_from_mcp
    from mira.orchestration.specialists.advisor import advisor_registry_entry
    from mira.orchestration.specialists.facets import facet_registry_entries

    registry = base if base is not None else AgentCardRegistry()
    vantage_tools = [
        tool
        for tool in mcp_tools
        if str(getattr(tool, "name", "") or "").startswith("vantage.")
    ]
    if vantage_tools:
        bridged = registered_tools_from_mcp(vantage_tools)
        # The advisor (position/tax) plus the analyze-graph facets
        # (technical/fundamental/news), all over the same vantage.* surface.
        card, factory = advisor_registry_entry(bridged)
        registry.register(card, factory)
        for card, factory in facet_registry_entries(bridged):
            registry.register(card, factory)
    return registry


__all__ = [
    "FINANCE_CARD",
    "RESEARCH_CARD",
    "build_demo_registry",
    "build_live_registry",
    "docs_registered_tools",
    "ledger_registered_tools",
]
