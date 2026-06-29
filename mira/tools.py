"""Provider-backed tools the agent can call on demand.

These wrap a DataProvider so the deep agent (and its sub-agents) can pull just the
data they need. The provider is bound at build time; the tools are generic.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from .providers.base import DataProvider


def _summarize(rows, max_rows: int = 60) -> str:
    """Compact, token-bounded JSON for the model (tail of the data)."""
    if isinstance(rows, dict):
        return json.dumps(rows, default=str)[:8000]
    if not rows:
        return "[]"
    tail = rows[-max_rows:]
    return json.dumps(tail, default=str)[:12000]


def make_tools(provider: DataProvider) -> list:
    """Build the tool list bound to `provider`. One generic read tool + a catalog."""

    @tool
    def list_resources() -> str:
        """List the data resources available to read (e.g. grades, scorecard, recommendations)."""
        return ", ".join(provider.resources())

    @tool
    def read_resource(resource: str, limit: int = 60) -> str:
        """Read a named data resource as JSON. `resource` must be one of list_resources().
        `limit` bounds how many recent records are returned (for JSONL resources)."""
        try:
            rows = provider.read(resource, limit=limit)
        except KeyError as e:
            return f"ERROR: {e}"
        return _summarize(rows, max_rows=limit)

    return [list_resources, read_resource]
