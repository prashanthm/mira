"""Provider-backed tools the agent can call on demand.

These wrap a DataProvider so the deep agent (and its sub-agents) can pull just the
data they need. The provider is bound at build time; the tools are generic.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from .providers.base import DataProvider


def _summarize(rows, max_rows: int = 40) -> str:
    """Compact, token-bounded JSON for the model (tail of the data).

    Local models drown in big JSON, so this caps both row count and total chars.
    """
    if isinstance(rows, dict):
        return json.dumps(rows, default=str)[:4000]
    if not rows:
        return "[]"
    tail = rows[-max_rows:]
    return json.dumps(tail, default=str)[:6000]


def make_tools(provider: DataProvider, lessons_path: str | None = None) -> list:
    """Build the tool list bound to `provider`. Generic read tools + (optional) lessons memory."""

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

    tools = [list_resources, read_resource]

    if lessons_path is not None:
        @tool
        def read_lessons() -> str:
            """Read Mira's durable lessons memory (the learnings accumulated over past runs),
            so you can decide whether today's observations reinforce an existing lesson (by id)
            or are new."""
            import json as _j
            from .memory import active, load_lessons
            ls = active(load_lessons(lessons_path))
            return _j.dumps([{"id": l.id, "text": l.text, "category": l.category,
                              "occurrences": l.occurrences, "last_seen": l.last_seen} for l in ls])
        tools.append(read_lessons)

    return tools
