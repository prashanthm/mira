"""The SPX-analyst specialist — answers "what will price do?" from an intraday
snapshot.

Given the chart-centric snapshot Vantage builds (current price + the coach's
playbook levels + live technicals + the ICT structures: unswept liquidity,
active order blocks, fresh FVGs, and the level-based draw), this specialist
produces a STRUCTURED, SCOREABLE directional forecast — bias, the expected path,
level targets it expects price to reach/reject, an invalidation, and a
confidence. On-demand and persisted; Vantage later scores the forecast against
the elapsed price action.

Two-step, same shape as trade review: Vantage owns the DATA (vantage.
spx_snapshot returns the snapshot); this specialist owns the JUDGMENT (the
forecast). No fan-out — a routed /turn reasoning loop.

The machine-readable ref line the inference parses:
    SPX_SNAPSHOT_REF day=2026-07-16 as_of=2026-07-16T12:00:00-04:00 underlying=SPX
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from mira.orchestration.agent_cards import AgentCard, card_for_domain
from mira.orchestration.ui_contract import with_contract
from mira.orchestration.specialist_scaffold import (
    DomainSpec,
    ReasoningBudget,
    RegisteredTool,
    SpecialistSubgraph,
    build_specialist_subgraph,
)

_REF = re.compile(
    r"SPX_SNAPSHOT_REF\s+day=(\S+)(?:\s+as_of=(\S+))?(?:\s+underlying=(\S+))?")


def _infer_snapshot(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """Fetch the intraday snapshot via vantage.spx_snapshot from the ref line.
    The analyst then reasons over it — Vantage owns the data, Mira owns the read."""
    m = _REF.search(action or "")
    tool = registry.get("vantage.spx_snapshot")
    if m is None or tool is None:
        return None
    args: dict[str, Any] = {"day": m.group(1)}
    if m.group(2):
        args["as_of"] = m.group(2)
    if m.group(3):
        args["underlying"] = m.group(3)
    try:
        return tool.handler(args)
    except Exception:  # noqa: BLE001 — a fetch failure degrades, never crashes
        return None


SPX_DOMAIN = DomainSpec(
    domain_id="spx_analyst",
    tool_prefixes=frozenset({"vantage."}),
)

SPX_ANALYST_CARD: AgentCard = card_for_domain(
    SPX_DOMAIN,
    model_hint="deep",
    description=(
        "The SPX intraday analyst — answers 'what will price do?' from a chart "
        "snapshot (price, the playbook levels, live technicals, and the ICT "
        "structures: unswept liquidity, order blocks, fresh FVGs, the draw). "
        "Produces a structured, scoreable directional forecast: bias, expected "
        "path, level targets, invalidation, confidence. On-demand, persisted, "
        "later scored against the elapsed price action."
    ),
    keywords=frozenset({
        "what will price do", "forecast", "spx", "0dte", "intraday", "draw",
        "liquidity", "order block", "fvg", "sweep", "path", "propensity",
        "where is price going", "bias", "snapshot", "next move",
    }),
    synthesis_hint=with_contract(
        "Answer WHAT WILL PRICE DO from the snapshot. Reason like an ICT desk: "
        "read the DRAW (the level-based magnet in the snapshot — where price is "
        "pulled), the unswept liquidity (BSL above / SSL below — likely raid "
        "targets), the active order blocks (support/resistance zones), the fresh "
        "FVGs, and the technicals (VWAP side, RSI, rel-volume). Cite ONLY the "
        "numbers in the snapshot. Produce a SCOREABLE forecast:\n"
        "- a `keyvals` section: Bias (up/down/range), Draw (the magnet + why), "
        "Confidence (low/med/high).\n"
        "- a `list` 'Expected path' — the ordered moves you expect (e.g. 'sweep "
        "SSL 7506, then reclaim toward max-pain 7529').\n"
        "- a `keyvals` 'Targets & invalidation': Target (the level(s) price "
        "should reach), Invalidation (the level that voids the read).\n"
        "- a `callout` one-line net call.\n"
        "Be decisive but honest about confidence. Educational, not advice. Note "
        "the levels are the nightly EOD estimate, 0DTE-blind."
    ),
)

REPRESENTATIVE_SPX_QUERY = "What will SPX price do from here based on the chart?"


def build_spx_analyst_specialist(
    tools: list[RegisteredTool] | None = None,
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """The spx-analyst subgraph. Reasons over the snapshot carried in / fetched
    for the prompt; binds the vantage. tools for the spx_snapshot fetch."""
    return build_specialist_subgraph(
        SPX_DOMAIN,
        list(tools or []),
        budget=budget or ReasoningBudget(max_steps=4),
        query_inference=_infer_snapshot,
    )


def spx_analyst_registry_entry(
    tools: Sequence[RegisteredTool] | None = None,
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory, ready for ``AgentCardRegistry.register``."""
    return SPX_ANALYST_CARD, lambda: build_spx_analyst_specialist(list(tools or []))


__all__ = [
    "SPX_ANALYST_CARD",
    "SPX_DOMAIN",
    "REPRESENTATIVE_SPX_QUERY",
    "build_spx_analyst_specialist",
    "spx_analyst_registry_entry",
]
