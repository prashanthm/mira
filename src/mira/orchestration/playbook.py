"""0DTE SPX playbook provider — fetch the scaffold, narrate it, cache.

The deterministic scaffold is computed nightly in Vantage and served over the
``vantage.spx_playbook`` MCP tool. Mira's job is only to *narrate* it: pull the
scaffold, run it through :func:`synthesize_playbook` (templated draft → LLM
plain-English polish), and cache the result. No fan-out, no specialists — one
tool call + one synthesis. Mirrors ``cached_analyze_provider`` in shape so the
service wires it identically.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mira.orchestration.synthesis import playbook_template, synthesize_playbook
from mira.providers.protocols import ILLMProvider

_TOOL_NAME = "vantage.spx_playbook"


def _find_playbook_tool(tools: list[Any]):
    for t in tools or []:
        name = getattr(getattr(t, "contract", None), "name", "") or getattr(t, "name", "")
        if name == _TOOL_NAME:
            return t
    return None


def _extract_scaffold(result: Any) -> dict[str, Any] | None:
    """The MCP tool returns an envelope: {available, playbook:{scaffold,...}, ...}.
    Pull the scaffold dict out, tolerating shape drift."""
    if not isinstance(result, dict):
        return None
    if result.get("available") is False:
        return None
    pb = result.get("playbook")
    if isinstance(pb, dict):
        scaffold = pb.get("scaffold")
        if isinstance(scaffold, dict):
            return scaffold
    # already a bare scaffold?
    if "level_ladder" in result or "setups" in result:
        return result
    return None


def build_playbook_result(
    tools: list[Any],
    *,
    llm: ILLMProvider | None = None,
    date: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Fetch the SPX playbook scaffold via MCP and narrate it.

    Returns ``{available, session, scaffold, narrative}`` on success.

    An ERROR (tool raised — e.g. the vantage tool now raises when the intraday
    map is missing or stale-dated) is surfaced as ``{available: False, error:
    <msg>}`` — NOT narrated. Mira must never paper over a stale/absent plan with
    confident prose; the missing/stale intraday map is exactly the failure we
    need loud. A benign "tool not wired" still degrades quietly (no error key)."""
    tool = _find_playbook_tool(tools)
    if tool is None:
        return {"available": False, "reason": "spx_playbook tool not available"}
    try:
        result = tool.handler({"date": date} if date else {})
    except Exception as exc:  # tool raised → the plan is missing/stale. SURFACE it.
        return {"available": False, "error": f"playbook_error: {exc}"}

    scaffold = _extract_scaffold(result)
    if scaffold is None:
        # available:False with no scaffold from a non-raising tool = genuinely
        # nothing generated yet (benign). A stale row would have RAISED above.
        return {"available": False, "reason": "no playbook generated yet"}

    narrative = synthesize_playbook(llm, scaffold, context=context)
    return {
        "available": True,
        "session": scaffold.get("session"),
        "scaffold": scaffold,
        "narrative": narrative,
        # the templated draft is always available as a grounded fallback view
        "draft": playbook_template(scaffold),
    }


def cached_playbook_provider(
    tools: list[Any],
    *,
    llm: ILLMProvider | None = None,
) -> Callable[[str | None, bool], dict[str, Any] | None]:
    """In-memory cache over :func:`build_playbook_result`.

    ``provider(date, refresh)`` returns the narrated playbook for a date (latest
    when None); ``refresh`` regenerates (re-narrates). Cached by date so the LLM
    call happens once per session per day."""
    cache: dict[str, dict[str, Any]] = {}

    def provider(date: str | None = None, refresh: bool = False) -> dict[str, Any] | None:
        key = date or "latest"
        if refresh or key not in cache:
            result = build_playbook_result(tools, llm=llm, date=date)
            # Only cache a real, available playbook. Never freeze an error or an
            # empty behind the no-TTL cache — a stale/missing map must be re-asked
            # every request until it's genuinely fixed, or the poison sticks all
            # day (and "latest" would pin yesterday across the session rollover).
            if result.get("available"):
                cache[key] = result
            else:
                cache.pop(key, None)
                return result
        return cache[key]

    return provider


__all__ = ["build_playbook_result", "cached_playbook_provider"]
