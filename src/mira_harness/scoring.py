"""Trace-scoring harness (ADR-045): score a specialist result's decision trace.

Extracted to the agent-agnostic harness plane (ADR-050); ``evals.trace_scoring``
re-exports from here. Scores the ``SpecialistResult.to_dict()`` shape — which is
byte-compatible with the public ``TraceResult`` ``answer``/``events``/
``bound_exceeded`` fields (ADR-049), so foreign traces score identically.

Scores are structural and deterministic — they assert *how* an answer was
produced (visible plan, grounded in attributed sources, within budget, error
free), not its semantic quality. Semantic scoring belongs to the live-provider
eval profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

DIMENSIONS = ("has_plan", "grounded", "within_bounds", "error_free")


@dataclass(frozen=True, slots=True)
class TraceScore:
    """Per-dimension booleans plus the aggregate [0, 1] score."""

    has_plan: bool
    grounded: bool
    within_bounds: bool
    error_free: bool

    @property
    def score(self) -> float:
        checks = (self.has_plan, self.grounded, self.within_bounds, self.error_free)
        return sum(checks) / len(checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_plan": self.has_plan,
            "grounded": self.grounded,
            "within_bounds": self.within_bounds,
            "error_free": self.error_free,
            "score": self.score,
        }


def _is_grounded(answer: Mapping[str, Any]) -> bool:
    """An answer is grounded when it carries source attribution (ADR-045: claim→source).

    Provenance may sit at the top level or on any nested mapping value (the demo
    handlers attach a ``provenance`` dict with source_type/source_id).
    """
    if not isinstance(answer, Mapping) or not answer:
        return False
    prov = answer.get("provenance")
    if isinstance(prov, Mapping) and prov.get("source_type") and prov.get("source_id"):
        return True
    return any(
        isinstance(value, Mapping) and _is_grounded(value) for value in answer.values()
    )


def score_trace(result: Mapping[str, Any]) -> TraceScore:
    """Score one specialist-result dict (the ``SpecialistResult.to_dict`` shape)."""
    return TraceScore(
        has_plan=bool(result.get("plan_steps")),
        grounded=_is_grounded(result.get("answer") or {}),
        within_bounds=not result.get("bound_exceeded"),
        error_free=not result.get("error"),
    )


def score_run(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate scores across a run: mean score + per-dimension pass rates."""
    if not results:
        return {"mean_score": 0.0, "count": 0, "dimensions": {d: 0.0 for d in DIMENSIONS}}
    scores = [score_trace(result) for result in results]
    return {
        "mean_score": sum(s.score for s in scores) / len(scores),
        "count": len(scores),
        "dimensions": {
            dim: sum(1 for s in scores if getattr(s, dim)) / len(scores)
            for dim in DIMENSIONS
        },
    }


__all__ = ["DIMENSIONS", "TraceScore", "score_run", "score_trace"]
