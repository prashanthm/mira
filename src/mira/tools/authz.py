"""Authorization declaration helpers for MCP tool contracts (ADR-031).

Surfaces the entitlement declared on a tool contract for enforcement at the
inherited MCP boundary (mcp-server ADR-022). This module does not perform local
allow/deny decisions.
"""

from __future__ import annotations

from mira.tools.contract import ToolContract


def entitlement_for(contract: ToolContract) -> str:
    """Return the entitlement the MCP boundary must enforce for this tool."""
    return contract.required_entitlement
