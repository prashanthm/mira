"""Trading lessons memory over the long-term layer (ADR-017/ADR-018).

A *lesson* is a durable, grounded observation about the user's own trading —
"Thursday entries win 75% (n=8, CI 0.45-0.90) vs 38% baseline" — distilled from
Vantage's ``trade_stats`` *notable* buckets. Lessons live in the long-term
memory tier (:class:`mira.core.memory.LongTermMemory`), so this module is
framework-agnostic (core layer: no langgraph/langchain — see
``tools/lint_imports.py``).

The curation loop mirrors the legacy ``mira_lessons`` reinforce/new-lesson flow,
but on **grounded rails**: a candidate is only ever built from a bucket the
engine already scored, and never invents a number. Two integrity rules
(ADR-018) are load-bearing:

* **Only SIGNIFICANT buckets become lessons.** ``trade_stats`` marks a notable
  bucket ``significant: True`` only when its credible interval clears the
  baseline AND ``n >= min_n``. A bucket that separates but is too thin arrives
  with ``significant: False`` — :func:`propose_from_buckets` refuses it. Small-n
  noise never becomes a lesson.
* **An eval-gate governs confidence.** A lesson earns ``med``/``high`` (and
  becomes eligible to *influence advice*) only when its bucket is significant
  AND ``n`` clears a promotion threshold; otherwise it stays ``low`` /
  advisory-only. :meth:`Lesson.influential` is the single predicate the advisor
  and insights layers consult.

Every lesson carries the Vantage provenance block it was grounded in, plus the
``as_of`` the bucket was built and a ``reinforced_count`` that bumps each time a
later build re-confirms the same dimension+value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from mira.core.memory import LongTermMemory

Category = Literal[
    "equity-trend", "options-structure", "regime", "risk", "execution", "timing", "other"
]
Confidence = Literal["low", "med", "high"]

# Eval-gate: a lesson may influence advice only when its bucket is significant
# AND has at least this many trips. Below it, a lesson stays advisory-only.
INFLUENCE_MIN_N = 8
# n threshold separating "med" from "high" among influential lessons.
HIGH_CONFIDENCE_MIN_N = 20

# Keyed home for lessons inside the long-term store (retrieval namespace).
_KEY_PREFIX = "lesson:"

# Feature dimension → lesson category. Anything unmapped falls to "other".
_DIMENSION_CATEGORY: dict[str, Category] = {
    "day_of_week": "timing",
    "month": "timing",
    "hold_band": "timing",
    "daily_trend": "equity-trend",
    "trend": "equity-trend",
    "vol_percentile_band": "regime",
    "regime": "regime",
    "dte_band": "options-structure",
    "moneyness": "options-structure",
    "kind": "options-structure",
    "mfe_capture_band": "execution",
    "entry_unknown": "execution",
}


def _category_for(dimension: str) -> Category:
    return _DIMENSION_CATEGORY.get(dimension, "other")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(float(value) * 100)}%"


@dataclass(frozen=True, slots=True)
class Lesson:
    """One durable, grounded trading lesson distilled from a notable bucket."""

    id: str
    text: str
    category: Category
    evidence: str
    source_provenance: dict[str, Any]
    created_as_of: str
    confidence: Confidence
    reinforced_count: int = 0
    dimension: str = ""
    value: str = ""
    n: int = 0
    kind: str = ""  # "edge" | "leak"

    @property
    def influential(self) -> bool:
        """Whether this lesson is eligible to influence advice (the eval-gate).

        True only for a significant bucket (``confidence != "low"``) whose sample
        cleared :data:`INFLUENCE_MIN_N`. This is the single predicate the advisor
        and trade_review layers consult before treating a lesson as an *edge*
        rather than a mere "seen, not enough data" observation.
        """
        return self.confidence != "low" and self.n >= INFLUENCE_MIN_N

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "category": self.category,
            "evidence": self.evidence,
            "source_provenance": dict(self.source_provenance),
            "created_as_of": self.created_as_of,
            "confidence": self.confidence,
            "reinforced_count": self.reinforced_count,
            "dimension": self.dimension,
            "value": self.value,
            "n": self.n,
            "kind": self.kind,
            "influential": self.influential,
        }


def _confidence_for(n: int, *, significant: bool) -> Confidence:
    """Eval-gated confidence: low unless significant; med/high scaled by n."""
    if not significant:
        return "low"
    if n < INFLUENCE_MIN_N:
        return "low"
    return "high" if n >= HIGH_CONFIDENCE_MIN_N else "med"


def _lesson_id(dimension: str, value: str) -> str:
    return f"{dimension}={value}"


def propose_from_buckets(
    notable_buckets: Sequence[Mapping[str, Any]],
    baseline: float | None,
    *,
    provenance: Mapping[str, Any] | None = None,
    as_of: str = "",
) -> list[Lesson]:
    """Turn SIGNIFICANT notable buckets into candidate lessons.

    ``notable_buckets`` is the ``notable`` array from ``vantage.trade_stats`` —
    each row already carries ``{dimension, value, n, win_rate, ci_low, ci_high,
    kind, significant}``. Only rows with ``significant is True`` become lessons
    (small-n / non-notable buckets never do, per ADR-018). ``baseline`` is the
    engine's overall win-rate, cited in each lesson's text for comparison.

    Returns candidates in input order (the engine sorts notable by |edge|
    desc). The caller feeds each to :meth:`LessonsStore.reinforce_or_add`.
    """
    if baseline is None:
        return []
    prov = dict(provenance or {})
    lessons: list[Lesson] = []
    for bucket in notable_buckets:
        if bucket.get("significant") is not True:
            continue  # thin / non-separating buckets never become lessons
        dimension = str(bucket.get("dimension", ""))
        value = str(bucket.get("value", ""))
        n = int(bucket.get("n", 0) or 0)
        win_rate = bucket.get("win_rate")
        ci_low = bucket.get("ci_low")
        ci_high = bucket.get("ci_high")
        kind = str(bucket.get("kind", "edge"))
        verb = "win" if kind == "edge" else "lose"
        direction = "edge" if kind == "edge" else "leak"
        evidence = (
            f"{dimension}={value}: win {_pct(win_rate)} (n={n}, "
            f"CI {round(float(ci_low), 2) if ci_low is not None else 'n/a'}-"
            f"{round(float(ci_high), 2) if ci_high is not None else 'n/a'}) "
            f"vs {_pct(baseline)} baseline"
        )
        text = (
            f"{value} {dimension.replace('_', ' ')} entries {verb} more often — "
            f"{_pct(win_rate)} vs {_pct(baseline)} baseline (n={n}); a {direction} "
            "grounded in your own round-trips."
        )
        lessons.append(
            Lesson(
                id=_lesson_id(dimension, value),
                text=text,
                category=_category_for(dimension),
                evidence=evidence,
                source_provenance=dict(prov),
                created_as_of=as_of,
                confidence=_confidence_for(n, significant=True),
                reinforced_count=0,
                dimension=dimension,
                value=value,
                n=n,
                kind=kind,
            )
        )
    return lessons


@dataclass
class LessonsStore:
    """Curated trading-lessons memory over the long-term tier.

    Dedupes candidate lessons against the store by ``dimension=value``: a
    re-observed lesson is *reinforced* (``reinforced_count`` bumped, evidence and
    confidence refreshed from the newest build) rather than duplicated. Lessons
    persist through :class:`~mira.core.memory.LongTermMemory` so they survive as
    long-term memory items and are retrievable by substring query.
    """

    memory: LongTermMemory
    _lessons: dict[str, Lesson] = field(default_factory=dict)

    def _persist(self, lesson: Lesson) -> None:
        self.memory.write(
            f"{_KEY_PREFIX}{lesson.id}",
            lesson.text,
            metadata={"provenance": dict(lesson.source_provenance), **lesson.to_dict()},
        )

    def reinforce_or_add(self, candidate: Lesson) -> dict[str, str | None]:
        """Dedupe a candidate: reinforce an existing lesson or add a new one.

        Same ``dimension=value`` as an existing lesson → reinforce it (bump
        ``reinforced_count``, refresh evidence/confidence/n from the candidate's
        newer build) and return ``{"reinforced": id, "added": None}``. Otherwise
        add the candidate and return ``{"reinforced": None, "added": id}``.
        """
        existing = self._lessons.get(candidate.id)
        if existing is not None:
            updated = replace(
                candidate,
                reinforced_count=existing.reinforced_count + 1,
            )
            self._lessons[candidate.id] = updated
            self._persist(updated)
            return {"reinforced": candidate.id, "added": None}
        self._lessons[candidate.id] = candidate
        self._persist(candidate)
        return {"reinforced": None, "added": candidate.id}

    def ingest(
        self,
        notable_buckets: Sequence[Mapping[str, Any]],
        baseline: float | None,
        *,
        provenance: Mapping[str, Any] | None = None,
        as_of: str = "",
    ) -> dict[str, list[str]]:
        """Propose lessons from notable buckets and reinforce-or-add each.

        Convenience over :func:`propose_from_buckets` +
        :meth:`reinforce_or_add`; returns the ids that were ``added`` vs
        ``reinforced`` this pass.
        """
        added: list[str] = []
        reinforced: list[str] = []
        for candidate in propose_from_buckets(
            notable_buckets, baseline, provenance=provenance, as_of=as_of
        ):
            outcome = self.reinforce_or_add(candidate)
            if outcome["added"]:
                added.append(candidate.id)
            elif outcome["reinforced"]:
                reinforced.append(candidate.id)
        return {"added": added, "reinforced": reinforced}

    def all_lessons(self) -> list[Lesson]:
        """Every stored lesson, influential ones first, then |n| desc — stable."""
        return sorted(
            self._lessons.values(),
            key=lambda le: (not le.influential, -le.n, le.dimension, le.value),
        )

    def influential_lessons(self) -> list[Lesson]:
        """Only lessons that cleared the eval-gate (eligible to influence advice)."""
        return [le for le in self.all_lessons() if le.influential]


__all__ = [
    "HIGH_CONFIDENCE_MIN_N",
    "INFLUENCE_MIN_N",
    "Category",
    "Confidence",
    "Lesson",
    "LessonsStore",
    "propose_from_buckets",
]
