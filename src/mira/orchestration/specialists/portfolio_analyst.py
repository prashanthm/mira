"""The portfolio-analyst specialist — reads the whole 'portfolio DNA' and produces
RECOMMENDED ACTIONS.

Where the journal_analyst reviews a window of TRADES, this reviews the HOLDINGS
book: the currency-scoped diversification/concentration, dividend income, beta/PE
character, risk (vol/Sharpe/drawdown), winners/losers by gain %, per-account
concentration, and allocation drift that Vantage assembles in
vantage.portfolio_snapshot. It reasons like a portfolio analyst and ends in a
`donext` of concrete, sized, rationaled actions — because a read without actions
isn't worthwhile.

Vantage owns the DATA (all the math is in portfolio.py, exposed as the snapshot
tool); this specialist owns the JUDGMENT (the health read + the actions). No
fan-out — a routed /turn reasoning loop.

Actions are decision-SUPPORT, educational — never orders or execution (ADR-010).

The machine-readable ref line the inference parses:
    PORTFOLIO_SNAPSHOT_REF account=all
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

_REF = re.compile(r"PORTFOLIO_SNAPSHOT_REF\s+account=(\S+)")


def _infer_portfolio_dna(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """Fetch the portfolio DNA via vantage.portfolio_snapshot from the
    PORTFOLIO_SNAPSHOT_REF line. The specialist then judges it — Vantage owns the
    math, Mira owns the read + actions."""
    m = _REF.search(action or "")
    tool = registry.get("vantage.portfolio_snapshot")
    if m is None or tool is None:
        return None
    try:
        return tool.handler({"account": m.group(1)})
    except Exception:  # noqa: BLE001 — a fetch failure degrades, never crashes
        return None


PORTFOLIO_DOMAIN = DomainSpec(
    domain_id="portfolio_analyst",
    tool_prefixes=frozenset({"vantage."}),
)

PORTFOLIO_ANALYST_CARD: AgentCard = card_for_domain(
    PORTFOLIO_DOMAIN,
    model_hint="deep",
    description=(
        "The HOLDINGS portfolio analyst — reads the whole portfolio DNA "
        "(currency-scoped diversification/concentration, income, beta/PE, risk: "
        "vol/Sharpe/drawdown, winners/losers by gain %, per-account concentration, "
        "allocation drift) and produces a health read plus concrete recommended "
        "ACTIONS (trim / harvest / rebalance / diversify), each sized and "
        "rationaled. Currencies are never cross-summed."
    ),
    keywords=frozenset({
        "portfolio", "holdings", "diversification", "concentration", "allocation",
        "rebalance", "sharpe", "risk", "drawdown", "volatility", "beta",
        "winners", "losers", "dividend", "income", "yield", "sector",
        "trim", "harvest", "actions", "recommend", "book",
    }),
    synthesis_hint=with_contract(
        "You are a portfolio analyst reading the portfolio DNA in the bundle. "
        "Currencies are separate books — NEVER combine INR and USD; read each "
        "`by_currency` bucket on its own terms. "
        "Lead with a `keyvals` section 'Health' (concentration band + HHI, "
        "portfolio yield, beta, Sharpe/vol/drawdown when risk.available, largest "
        "single-name weight) with tone good/warn/bad. Add a `list` 'Key risks' "
        "citing the REAL numbers (single-name flags, sector overweight, "
        "single-account/broker concentration, low Sharpe, allocation drift) — "
        "cite only figures present in the bundle, never invent a holding. "
        "Then the point of the whole thing: a `donext` of RECOMMENDED ACTIONS, "
        "each `title` a concrete verb+target (e.g. 'Trim NVDA 38% -> 15%', "
        "'Harvest SQQQ loss', 'Rebalance: add $X intl equity') and `detail` the "
        "rationale + size from the bundle (drift $, gain %, tax benefit). "
        "Order actions by impact. These are decision-support and educational — "
        "NOT orders, never phrase as execution. If risk.available is false, say "
        "risk is data-gated (seed bars) rather than guessing."
    ),
)

REPRESENTATIVE_PORTFOLIO_QUERY = (
    "Analyze my portfolio and give me recommended actions."
)


def build_portfolio_analyst_specialist(
    tools: list[RegisteredTool] | None = None,
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """The portfolio-analyst subgraph. Reasons over the DNA carried in / fetched
    for the prompt; binds the vantage. tools for the portfolio_snapshot fetch."""
    return build_specialist_subgraph(
        PORTFOLIO_DOMAIN,
        list(tools or []),
        budget=budget or ReasoningBudget(max_steps=8),
        query_inference=_infer_portfolio_dna,
    )


def portfolio_analyst_registry_entry(
    tools: Sequence[RegisteredTool] | None = None,
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory, ready for ``AgentCardRegistry.register``."""
    return PORTFOLIO_ANALYST_CARD, lambda: build_portfolio_analyst_specialist(list(tools or []))


__all__ = [
    "PORTFOLIO_ANALYST_CARD",
    "PORTFOLIO_DOMAIN",
    "REPRESENTATIVE_PORTFOLIO_QUERY",
    "build_portfolio_analyst_specialist",
    "portfolio_analyst_registry_entry",
]
