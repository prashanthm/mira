"""Domain constants and MCP tool allow-lists."""

from __future__ import annotations

from mira.orchestration.specialist_scaffold import DomainSpec

RESEARCH_DOMAIN = DomainSpec(
    domain_id="research",
    tool_prefixes=frozenset({"docs."}),
)

FINANCE_DOMAIN = DomainSpec(
    domain_id="finance",
    tool_prefixes=frozenset({"ledger."}),
)

# First MCP-backed remote-tool domain (ADR-014 Phase V3): the specialist binds
# only tools discovered from the Vantage MCP server (``vantage.*``) — Mira does
# no portfolio math, it calls the engine and reshapes attributed answers.
ADVISOR_DOMAIN = DomainSpec(
    domain_id="advisor",
    tool_prefixes=frozenset({"vantage."}),
)
