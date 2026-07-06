"""Tests for the trading lessons store (mira.core.lessons, ADR-017/ADR-018).

The load-bearing integrity rules under test:

* Only SIGNIFICANT notable buckets become lessons — a thin bucket that separates
  from baseline but has n<min_n is NEVER promoted.
* The eval-gate: a lesson influences advice (``influential``) only when its
  bucket is significant AND its sample cleared the promotion threshold.
* Reinforce dedupe: a re-observed dimension=value bumps ``reinforced_count`` and
  refreshes evidence, never duplicates.

Buckets are the ``notable`` shape the Vantage ``trade_stats`` tool emits (see
tests/fake_vantage.TRADE_STATS_RESULT), grounded to real numbers (baseline
37.8%, Thursday edge n=8 significant, a deep_itm n=2 thin bucket).
"""

from __future__ import annotations

from typing import Any

from mira.core.lessons import (
    INFLUENCE_MIN_N,
    Lesson,
    LessonsStore,
    propose_from_buckets,
)
from mira.core.memory import InMemoryLongTermMemory

from tests.fake_vantage import TRADE_STATS_RESULT

BASELINE = 0.378378
NOTABLE = TRADE_STATS_RESULT["notable"]
PROVENANCE = TRADE_STATS_RESULT["provenance"]


def _store() -> LessonsStore:
    return LessonsStore(memory=InMemoryLongTermMemory())


# ── propose_from_buckets: only significant buckets ───────────────────────────


def test_propose_only_promotes_significant_buckets() -> None:
    lessons = propose_from_buckets(
        NOTABLE, BASELINE, provenance=PROVENANCE, as_of="2025-07-15"
    )
    # The fixture has one significant (Thursday) and one thin (deep_itm) notable.
    assert [le.dimension for le in lessons] == ["day_of_week"]
    assert all(le.value != "deep_itm" for le in lessons)


def test_small_n_bucket_never_becomes_a_lesson() -> None:
    thin_only = [b for b in NOTABLE if b.get("significant") is not True]
    assert thin_only, "fixture must include a thin notable bucket"
    assert propose_from_buckets(thin_only, BASELINE) == []


def test_lesson_evidence_carries_n_and_ci_and_baseline() -> None:
    lesson = propose_from_buckets(NOTABLE, BASELINE, provenance=PROVENANCE)[0]
    assert "n=8" in lesson.evidence
    assert "0.45" in lesson.evidence and "0.9" in lesson.evidence  # CI bounds
    assert "38% baseline" in lesson.evidence
    assert lesson.category == "timing"
    assert lesson.source_provenance["source_type"] == "vantage"
    assert lesson.n == 8


def test_no_baseline_yields_no_lessons() -> None:
    assert propose_from_buckets(NOTABLE, None) == []


# ── eval-gate: influence eligibility ─────────────────────────────────────────


def test_significant_bucket_at_threshold_is_influential() -> None:
    lesson = propose_from_buckets(NOTABLE, BASELINE)[0]
    assert lesson.n >= INFLUENCE_MIN_N
    assert lesson.confidence in {"med", "high"}
    assert lesson.influential is True


def test_significant_but_below_threshold_is_low_and_not_influential() -> None:
    # A bucket that is significant per the engine yet has n below the influence
    # threshold stays low-confidence / advisory-only.
    thin_significant = [
        {
            "dimension": "day_of_week",
            "value": "Monday",
            "n": INFLUENCE_MIN_N - 1,
            "win_rate": 0.7,
            "ci_low": 0.4,
            "ci_high": 0.9,
            "kind": "edge",
            "significant": True,
        }
    ]
    lesson = propose_from_buckets(thin_significant, BASELINE)[0]
    assert lesson.confidence == "low"
    assert lesson.influential is False


def test_high_confidence_requires_large_sample() -> None:
    big = [
        {
            "dimension": "day_of_week",
            "value": "Friday",
            "n": 40,
            "win_rate": 0.65,
            "ci_low": 0.5,
            "ci_high": 0.78,
            "kind": "edge",
            "significant": True,
        }
    ]
    lesson = propose_from_buckets(big, BASELINE)[0]
    assert lesson.confidence == "high"
    assert lesson.influential is True


# ── reinforce / add dedupe ───────────────────────────────────────────────────


def test_add_then_reinforce_same_dimension_value() -> None:
    store = _store()
    candidate = propose_from_buckets(NOTABLE, BASELINE, as_of="2025-07-15")[0]

    first = store.reinforce_or_add(candidate)
    assert first == {"reinforced": None, "added": candidate.id}
    assert len(store.all_lessons()) == 1

    # A later build re-observes the same dimension=value → reinforce, not dup.
    again = propose_from_buckets(NOTABLE, BASELINE, as_of="2025-07-22")[0]
    second = store.reinforce_or_add(again)
    assert second == {"reinforced": candidate.id, "added": None}
    assert len(store.all_lessons()) == 1
    assert store.all_lessons()[0].reinforced_count == 1


def test_reinforce_refreshes_evidence_to_newest_build() -> None:
    store = _store()
    store.reinforce_or_add(propose_from_buckets(NOTABLE, BASELINE)[0])

    refreshed_bucket = [dict(NOTABLE[0])]
    refreshed_bucket[0]["n"] = 12
    refreshed_bucket[0]["win_rate"] = 0.8
    store.reinforce_or_add(propose_from_buckets(refreshed_bucket, BASELINE)[0])

    lesson = store.all_lessons()[0]
    assert lesson.n == 12
    assert "n=12" in lesson.evidence
    assert lesson.reinforced_count == 1


def test_ingest_reports_added_and_reinforced_ids() -> None:
    store = _store()
    first = store.ingest(NOTABLE, BASELINE, provenance=PROVENANCE, as_of="2025-07-15")
    assert first["added"] == ["day_of_week=Thursday"]
    assert first["reinforced"] == []

    second = store.ingest(NOTABLE, BASELINE, provenance=PROVENANCE, as_of="2025-07-22")
    assert second["added"] == []
    assert second["reinforced"] == ["day_of_week=Thursday"]


# ── influential filter never leaks a thin bucket ─────────────────────────────


def test_influential_lessons_excludes_small_n() -> None:
    store = _store()
    # Ingest the real notable set (one significant, one thin) — the thin one is
    # dropped at propose time and can never reach influential_lessons().
    store.ingest(NOTABLE, BASELINE, provenance=PROVENANCE)
    # Add a significant-but-thin lesson explicitly to prove the gate holds.
    store.reinforce_or_add(
        propose_from_buckets(
            [
                {
                    "dimension": "month",
                    "value": "March",
                    "n": 3,
                    "win_rate": 0.9,
                    "ci_low": 0.5,
                    "ci_high": 0.99,
                    "kind": "edge",
                    "significant": True,
                }
            ],
            BASELINE,
        )[0]
    )
    influential = store.influential_lessons()
    assert [le.id for le in influential] == ["day_of_week=Thursday"]
    assert all(le.n >= INFLUENCE_MIN_N for le in influential)


# ── persistence via long-term memory ─────────────────────────────────────────


def test_lessons_persist_to_long_term_memory_and_are_retrievable() -> None:
    memory = InMemoryLongTermMemory()
    store = LessonsStore(memory=memory)
    store.ingest(NOTABLE, BASELINE, provenance=PROVENANCE)

    hits = memory.retrieve("Thursday")
    assert hits and any("Thursday" in h for h in hits)


def test_lesson_to_dict_is_json_shaped() -> None:
    lesson: Lesson = propose_from_buckets(NOTABLE, BASELINE, provenance=PROVENANCE)[0]
    payload: dict[str, Any] = lesson.to_dict()
    assert payload["influential"] is True
    assert set(payload) >= {
        "id",
        "text",
        "category",
        "evidence",
        "source_provenance",
        "confidence",
        "reinforced_count",
        "n",
        "influential",
    }
