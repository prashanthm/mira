"""The journal-analyst specialist — the AGGREGATE self-assessment of a desk.

Where the trade_analyst reviews ONE trade, this reviews a WINDOW of them: it
reads the deterministic bundle Vantage assembles (rubric scores, a pattern
census with trade citations, per-day discipline, the per-trade review excerpts,
and the PRIOR journal analysis) and writes the JOURNAL ANALYSIS — a SWOT plus a
scored read that BUILDS ON the prior one, so the operator's knowledge compounds.

Two-step, same shape as trade review: Vantage owns the DATA (vantage.
journal_analysis returns the bundle + a ready-made prompt); this specialist
owns the JUDGMENT (the prose SWOT + score narrative). No fan-out — a routed
/turn reasoning loop.

The machine-readable ref line the inference parses:
    JOURNAL_REF from=2026-07-13 to=2026-07-15 underlying=SPX
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from mira.orchestration.agent_cards import AgentCard, card_for_domain
from mira.orchestration.specialist_scaffold import (
    DomainSpec,
    ReasoningBudget,
    RegisteredTool,
    SpecialistSubgraph,
    build_specialist_subgraph,
)

_REF = re.compile(r"JOURNAL_REF\s+from=(\S+)\s+to=(\S+)\s+underlying=(\S+)")


def _infer_journal_bundle(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """Fetch the window's journal-analysis bundle via vantage.journal_analysis
    from the JOURNAL_REF line. The specialist then narrates it — Vantage owns
    the aggregation, Mira owns the SWOT + read."""
    m = _REF.search(action or "")
    tool = registry.get("vantage.journal_analysis")
    if m is None or tool is None:
        return None
    try:
        return tool.handler({"window_from": m.group(1), "window_to": m.group(2),
                             "underlying": m.group(3)})
    except Exception:  # noqa: BLE001 — a fetch failure degrades, never crashes
        return None


JOURNAL_DOMAIN = DomainSpec(
    domain_id="journal_analyst",
    tool_prefixes=frozenset({"vantage."}),
)

JOURNAL_ANALYST_CARD: AgentCard = card_for_domain(
    JOURNAL_DOMAIN,
    model_hint="deep",
    description=(
        "The AGGREGATE journal analyst — reviews a WINDOW of trades, not one. "
        "Reads the desk's rubric scores, recurring-mistake census (with the "
        "trades that evidence each), per-day discipline, and the prior journal "
        "analysis, and writes a SWOT plus a scored read that builds on the "
        "prior one so the operator's self-knowledge compounds over time."
    ),
    keywords=frozenset({
        "journal", "swot", "aggregate", "assessment", "self-assessment",
        "weekly", "monthly", "scorecard", "rubric", "patterns", "recurring",
        "overall", "period", "compounding", "improving",
    }),
    synthesis_hint=(
        "Produce a JOURNAL ANALYSIS of this WINDOW of trades from the bundle as "
        "a SINGLE JSON OBJECT (no prose, no markdown fences) — the Vantage UI "
        "renders it into a SWOT grid. The exact JSON shape is given IN the "
        "prompt (keys: headline, swot{strengths,weaknesses,opportunities,"
        "threats}, pattern, scores_read, do_next); follow it exactly. Strengths "
        "& weaknesses carry `cites` of real trade labels + $ from the bundle — "
        "never invent a trade. Build on the prior analysis in `scores_read` "
        "when present. Be direct; educational, not financial advice. Output the "
        "JSON and nothing else."
    ),
)

REPRESENTATIVE_JOURNAL_QUERY = (
    "Write a journal analysis and SWOT of my trades this week with a scorecard."
)


def build_journal_analyst_specialist(
    tools: list[RegisteredTool] | None = None,
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """The journal-analyst subgraph. Reasons over the bundle carried in / fetched
    for the prompt; binds the vantage. tools for the journal_analysis fetch."""
    return build_specialist_subgraph(
        JOURNAL_DOMAIN,
        list(tools or []),
        budget=budget or ReasoningBudget(max_steps=4),
        query_inference=_infer_journal_bundle,
    )


def journal_analyst_registry_entry(
    tools: Sequence[RegisteredTool] | None = None,
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory, ready for ``AgentCardRegistry.register``."""
    return JOURNAL_ANALYST_CARD, lambda: build_journal_analyst_specialist(list(tools or []))


__all__ = [
    "JOURNAL_ANALYST_CARD",
    "JOURNAL_DOMAIN",
    "REPRESENTATIVE_JOURNAL_QUERY",
    "build_journal_analyst_specialist",
    "journal_analyst_registry_entry",
]
