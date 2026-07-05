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
