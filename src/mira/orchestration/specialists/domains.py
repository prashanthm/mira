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

# Multi-facet analysis domains (the analyze graph). Each fans one query to ONE
# facet tool and returns the attributed result; the synthesis node weaves them.
# All bind the ``vantage.*`` surface (filtered per-facet by their inference to a
# single tool), so no portfolio math happens in Mira.
TECHNICAL_DOMAIN = DomainSpec(
    domain_id="technical",
    tool_prefixes=frozenset({"vantage."}),
)

FUNDAMENTAL_DOMAIN = DomainSpec(
    domain_id="fundamental",
    tool_prefixes=frozenset({"vantage."}),
)

NEWS_DOMAIN = DomainSpec(
    domain_id="news",
    tool_prefixes=frozenset({"vantage."}),
)
