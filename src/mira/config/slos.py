"""SLOs-as-code with event-count error budgets (ADR-043).

An agent surface fails differently from a CRUD API, so its objectives live in
code next to the service rather than in a dashboard: each :class:`Slo` names an
indicator, a target ratio, and an event-count accounting window. Windows are
event-based (the last ``window_events`` outcomes) so tracking is deterministic
and needs no wall clock — wall-clock (calendar) windowing is deferred.

The tracker is the measurement half; the burn *policy* (what happens when a
budget exhausts) belongs to the ADR-044 incident workflow, which consumes
:class:`SloStatus` via ``IncidentDetector.from_slo``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Slo:
    """One service-level objective: target ratio over an event-count window."""

    name: str
    description: str
    objective: float
    window_events: int

    def __post_init__(self) -> None:
        if not 0.0 < self.objective <= 1.0:
            raise ValueError(f"objective must be in (0, 1], got {self.objective}")
        if self.window_events < 1:
            raise ValueError(f"window_events must be >= 1, got {self.window_events}")


@dataclass(frozen=True, slots=True)
class SloStatus:
    """Point-in-time SLO accounting over the tracked window.

    ``error_budget_total`` is ``(1 - objective) * total`` — the number of bad
    events the window tolerates; ``error_budget_spent`` is the observed bad
    count; ``error_budget_remaining_ratio`` is the unspent fraction clamped to
    ``[0, 1]``. With zero recorded events the SLO is vacuously healthy.
    """

    slo: Slo
    good: int
    total: int
    achieved_ratio: float
    error_budget_total: float
    error_budget_spent: int
    error_budget_remaining_ratio: float
    healthy: bool


class SloTracker:
    """Ring-buffer SLO tracker: keeps the last ``window_events`` outcomes per SLO.

    Deterministic and clock-free — ``record`` appends a good/bad outcome and
    the window slides by event count, so tests (and replays) are exact.
    """

    def __init__(self, slos: tuple[Slo, ...] | list[Slo] | None = None) -> None:
        self._slos: dict[str, Slo] = {}
        self._outcomes: dict[str, deque[bool]] = {}
        for slo in slos if slos is not None else DEFAULT_SLOS:
            self.register(slo)

    def register(self, slo: Slo) -> None:
        """Add (or replace) an SLO; replacing resets its window."""
        self._slos[slo.name] = slo
        self._outcomes[slo.name] = deque(maxlen=slo.window_events)

    @property
    def slos(self) -> tuple[Slo, ...]:
        return tuple(self._slos.values())

    def record(self, slo_name: str, good: bool) -> None:
        """Record one outcome for the named SLO (oldest event falls out)."""
        self._require(slo_name)
        self._outcomes[slo_name].append(good)

    def status(self, slo_name: str) -> SloStatus:
        """Compute current window accounting for the named SLO."""
        slo = self._require(slo_name)
        outcomes = self._outcomes[slo_name]
        total = len(outcomes)
        good = sum(1 for outcome in outcomes if outcome)
        bad = total - good

        if total == 0:
            # Vacuously healthy: no events means no evidence of burn.
            return SloStatus(
                slo=slo,
                good=0,
                total=0,
                achieved_ratio=1.0,
                error_budget_total=0.0,
                error_budget_spent=0,
                error_budget_remaining_ratio=1.0,
                healthy=True,
            )

        achieved_ratio = good / total
        error_budget_total = (1.0 - slo.objective) * total
        if error_budget_total > 0:
            remaining = (error_budget_total - bad) / error_budget_total
        else:
            # objective == 1.0: any bad event exhausts a zero-size budget.
            remaining = 1.0 if bad == 0 else 0.0
        remaining_ratio = min(1.0, max(0.0, remaining))

        return SloStatus(
            slo=slo,
            good=good,
            total=total,
            achieved_ratio=achieved_ratio,
            error_budget_total=error_budget_total,
            error_budget_spent=bad,
            error_budget_remaining_ratio=remaining_ratio,
            healthy=achieved_ratio >= slo.objective,
        )

    def _require(self, slo_name: str) -> Slo:
        slo = self._slos.get(slo_name)
        if slo is None:
            raise KeyError(f"unknown SLO {slo_name!r}")
        return slo


# SLOs-as-code for the reference agent surface (ADR-043). Each SLI is a
# good/bad classification the caller records per event:
#
# - turn-success: a run_turn completed without an unhandled error or a
#   guardrail hard-block. 99% over the last 1000 turns.
# - turn-latency-under-budget: the turn finished within its latency budget
#   (the caller classifies against the ADR-013 loop budget). Latency is a
#   ratio-of-good-events SLI rather than a percentile so the event-count
#   window stays deterministic. 95% over the last 1000 turns.
# - eval-gate-pass: an ADR-045 eval-gate execution passed. 99% over the last
#   100 gate runs — quality regressions burn this budget before they show up
#   as user-visible errors.
DEFAULT_SLOS: tuple[Slo, ...] = (
    Slo(
        name="turn-success",
        description="Agent turns that complete without error or hard guardrail block.",
        objective=0.99,
        window_events=1000,
    ),
    Slo(
        name="turn-latency-under-budget",
        description="Agent turns that finish within the per-turn latency budget.",
        objective=0.95,
        window_events=1000,
    ),
    Slo(
        name="eval-gate-pass",
        description="ADR-045 eval-gate executions that pass.",
        objective=0.99,
        window_events=100,
    ),
)


def slo_health_payload(tracker: SloTracker) -> dict[str, Any]:
    """JSON-safe SLO summary keyed by SLO name, for /health surfacing."""
    payload: dict[str, Any] = {}
    for slo in tracker.slos:
        status = tracker.status(slo.name)
        payload[slo.name] = {
            "objective": slo.objective,
            "window_events": slo.window_events,
            "good": status.good,
            "total": status.total,
            "achieved_ratio": status.achieved_ratio,
            "error_budget_total": status.error_budget_total,
            "error_budget_spent": status.error_budget_spent,
            "error_budget_remaining_ratio": status.error_budget_remaining_ratio,
            "healthy": status.healthy,
        }
    return payload


__all__ = [
    "DEFAULT_SLOS",
    "Slo",
    "SloStatus",
    "SloTracker",
    "slo_health_payload",
]
