"""The forecast-grader specialist — grades a REPLAY FORECAST run.

Where the spx_analyst answers "what will price do?" at ONE moment, a Replay
Forecast fires that question at every interval step through a chosen day. This
specialist reads the deterministic bundle Vantage assembles for a run (every
forecast WITH its CODE-computed accuracy score, the calibration hit-rates
bucketed by time-of-day / bias / tier, a per-step digest, and the PRIOR
calibration) and grades how the analyst's read EVOLVED as the tape developed.

Anti-reward-hacking by construction: the SCORE NUMBERS are computed in Python
(vantage.replay_forecasts returns them); this grader ONLY reads and narrates
them — it never computes, alters, or invents a score. The forecasting analyst
never sees these grades (the calibration memory is grader-owned, read-only), so
there is no feedback path to game.

Two-step, same shape as the journal analyst: Vantage owns the DATA (the bundle +
a ready-made prompt); this specialist owns the JUDGMENT (the prose read over the
already-computed scores). No fan-out — a routed /turn reasoning loop.

The machine-readable ref line the inference parses:
    FORECAST_GRADE_REF run_id=rf-SPX-2026-07-16-...
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

_REF = re.compile(r"FORECAST_GRADE_REF\s+run_id=(\S+)")


def _infer_grade_bundle(action: str, registry: dict[str, RegisteredTool]) -> dict[str, Any] | None:
    """Fetch the run's graded bundle via vantage.replay_forecasts from the
    FORECAST_GRADE_REF line. The grader then narrates the CODE-computed scores —
    Vantage owns the numbers, Mira owns the read."""
    m = _REF.search(action or "")
    tool = registry.get("vantage.replay_forecasts")
    if m is None or tool is None:
        return None
    try:
        return tool.handler({"run_id": m.group(1)})
    except Exception:  # noqa: BLE001 — a fetch failure degrades, never crashes
        return None


FORECAST_GRADER_DOMAIN = DomainSpec(
    domain_id="forecast_grader",
    tool_prefixes=frozenset({"vantage."}),
)

FORECAST_GRADER_CARD: AgentCard = card_for_domain(
    FORECAST_GRADER_DOMAIN,
    model_hint="deep",
    description=(
        "The REPLAY FORECAST grader — reviews a whole day's SEQUENCE of "
        "intraday forecasts, not one. Reads the run's code-computed accuracy "
        "scores (hit-rate overall + by time-of-day / bias / hourly tier), the "
        "per-step verdicts, and the prior calibration, then grades how the "
        "analyst's read evolved as price developed — early, late, whipsawed, or "
        "well-adapted. It NARRATES the already-computed scores; it never invents "
        "a number. Its calibration memory is never fed back to the forecaster."
    ),
    keywords=frozenset({
        "grade", "grader", "replay", "calibration", "hit rate", "accuracy",
        "forecast run", "how good", "evolved", "sequence", "scorecard",
        "was the forecast right", "coach the analyst", "compounding",
    }),
    synthesis_hint=with_contract(
        "Grade this REPLAY FORECAST run from the bundle. The SCORES ARE ALREADY "
        "COMPUTED and provided — read and narrate them; NEVER compute, alter, or "
        "invent a score or hit-rate, and cite ONLY grounded numbers from the "
        "bundle. Buckets flagged insufficient have too small a sample: say "
        "'insufficient sample', do not fabricate a rate.\n"
        "\n"
        "Lead with a `scorecard` section whose rows present the bundle's "
        "hit-rates as 0-100 (multiply the code hit_rate by 100): an 'Overall' "
        "row, then the by-time / by-bias / by-tier buckets that have enough "
        "sample. Add a `callout` (tone good/bad/warn) for the single biggest "
        "calibration finding — where the analyst read best or worst. Add a "
        "`prose` section that grades the SEQUENCE: where the read flipped, where "
        "it held correctly, whether it was early or late — and that BUILDS ON the "
        "prior calibration so the assessment compounds. Close with a `donext` of "
        "3-4 concrete things the analyst should read differently next time. "
        "Be direct; educational, not financial advice."
    ),
)

REPRESENTATIVE_GRADE_QUERY = (
    "Grade this replay forecast run — how good was the analyst through the day?"
)


def build_forecast_grader_specialist(
    tools: list[RegisteredTool] | None = None,
    *,
    budget: ReasoningBudget | None = None,
) -> SpecialistSubgraph:
    """The forecast-grader subgraph. Reasons over the bundle carried in / fetched
    for the prompt; binds the vantage. tools for the replay_forecasts fetch."""
    return build_specialist_subgraph(
        FORECAST_GRADER_DOMAIN,
        list(tools or []),
        budget=budget or ReasoningBudget(max_steps=4),
        query_inference=_infer_grade_bundle,
    )


def forecast_grader_registry_entry(
    tools: Sequence[RegisteredTool] | None = None,
) -> tuple[AgentCard, Callable[[], SpecialistSubgraph]]:
    """Card + lazy factory, ready for ``AgentCardRegistry.register``."""
    return FORECAST_GRADER_CARD, lambda: build_forecast_grader_specialist(list(tools or []))


__all__ = [
    "FORECAST_GRADER_CARD",
    "FORECAST_GRADER_DOMAIN",
    "REPRESENTATIVE_GRADE_QUERY",
    "build_forecast_grader_specialist",
    "forecast_grader_registry_entry",
]
