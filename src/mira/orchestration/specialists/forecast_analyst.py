"""The forecast-analyst specialist — answers "what will price do?" from an
intraday snapshot, for ANY ticker (SPX/QQQ/IWM/…, keyed on the snapshot's
`underlying`).

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

The machine-readable ref line the inference parses (SPX_SNAPSHOT_REF is the wire
marker name — it carries `underlying` for any ticker):
    SPX_SNAPSHOT_REF day=2026-07-16 as_of=2026-07-16T12:00:00-04:00 underlying=QQQ
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


FORECAST_DOMAIN = DomainSpec(
    domain_id="forecast_analyst",
    tool_prefixes=frozenset({"vantage."}),
)

FORECAST_ANALYST_CARD: AgentCard = card_for_domain(
    FORECAST_DOMAIN,
    model_hint="deep",
    description=(
        "The intraday forecast analyst (any ticker) — answers 'what will price do?' from a chart "
        "snapshot (price, the playbook levels, live technicals, and the ICT "
        "structures: unswept liquidity, order blocks, fresh FVGs, the draw). "
        "Produces a structured, scoreable directional forecast: bias, expected "
        "path, level targets, invalidation, confidence. On-demand, persisted, "
        "later scored against the elapsed price action."
    ),
    # single tokens only — the matcher splits the query on whitespace, so a
    # space-containing keyword can NEVER match (routing audit 2026-07-25).
    keywords=frozenset({
        "forecast", "spx", "0dte", "intraday", "draw", "liquidity", "fvg",
        "sweep", "path", "propensity", "bias", "snapshot", "headed",
        "afternoon", "close", "going", "move", "direction",
    }),
    synthesis_hint=with_contract(
        "Answer WHAT WILL PRICE DO from the snapshot. Reason like an ICT desk: "
        "read the DRAW (the level-based magnet in the snapshot — where price is "
        "pulled), the unswept liquidity (BSL above / SSL below — likely raid "
        "targets), the active order blocks (support/resistance zones), the fresh "
        "FVGs, and the technicals (VWAP side, RSI, rel-volume). Cite ONLY the "
        "numbers in the snapshot. TARGET DISCIPLINE: set `target` to the NEAREST "
        "high-probability level in your called direction (the closest playbook level, "
        "unswept liquidity pool, order block, or the draw) — NOT the most ambitious "
        "one. Intraday moves are usually small; a target within roughly 1 ATR of "
        "current price is far more likely to be reached than a distant one. Prefer a "
        "conservative, reachable target over a big round number. If the snapshot's "
        "`ict_htf` block has "
        "present=true, there is a BACKTEST-VALIDATED hourly setup: state its tier "
        "(A+/B) and direction, and add a line to the Expected path — 'hourly "
        "setup present (tier, dir) → look to a lower timeframe (5m/1m) for entry "
        "timing'. This is a HEADS-UP, not a fired entry; do not present it as an "
        "executed trade. Produce a SCOREABLE forecast.\n"
        "\n"
        "TWO OUTPUTS, both required:\n"
        "\n"
        "(A) The human-readable sections (as usual): a `keyvals` Bias/Draw/"
        "Confidence, a `list` 'Expected path' (the ordered moves, in prose), a "
        "`keyvals` 'Targets & invalidation', and a `callout` net call.\n"
        "\n"
        "(B) A machine-readable `plot` object at the TOP LEVEL of your JSON (a "
        "sibling of `headline` and `sections`) — Vantage plots this DIRECTLY on the "
        "chart, so it must be clean structured numbers, NOT prose:\n"
        '  "plot": {\n'
        '    "bias": "up" | "down" | "range",\n'
        '    "target": <number>,          // the single primary destination level\n'
        '    "invalidation": <number>,    // the level that voids the read\n'
        '    "path": [                     // 2–5 ordered steps price should visit\n'
        '      {"seq":1, "price":<number>, "dir":"up"|"down", "note":"<short reason>"},\n'
        '      ... ] }\n'
        "RULES for `plot`: every price is a bare number (no text). The `path` is the "
        "ordered sequence price should trade through, and it MUST include the "
        "`target` as one of its steps (the path has to visibly REACH the target — "
        "if the target is the destination, it is the final step; if price overshoots "
        "past it, include the target as an intermediate step). Keep `note` under ~6 "
        "words. The path, target, and bias in `plot` must AGREE with what you wrote "
        "in the human sections.\n"
        "\n"
        "Be decisive but honest about confidence. Educational, not advice. Note "
        "the levels are the nightly EOD estimate, 0DTE-blind."
    ),
)

REPRESENTATIVE_FORECAST_QUERY = "What will SPX price do from here based on the chart?"


def build_forecast_analyst_specialist(
    tools: list[RegisteredTool] | None = None,
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """The forecast-analyst subgraph. Reasons over the snapshot carried in / fetched
    for the prompt; binds the vantage. tools for the spx_snapshot fetch."""
    return build_specialist_subgraph(
        FORECAST_DOMAIN,
        list(tools or []),
        budget=budget or ReasoningBudget(max_steps=8),
        query_inference=_infer_snapshot,
    )


def forecast_analyst_registry_entry(
    tools: Sequence[RegisteredTool] | None = None,
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory, ready for ``AgentCardRegistry.register``."""
    return FORECAST_ANALYST_CARD, lambda: build_forecast_analyst_specialist(list(tools or []))


__all__ = [
    "FORECAST_ANALYST_CARD",
    "FORECAST_DOMAIN",
    "REPRESENTATIVE_FORECAST_QUERY",
    "build_forecast_analyst_specialist",
    "forecast_analyst_registry_entry",
]
