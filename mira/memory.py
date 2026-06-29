from __future__ import annotations
"""
Lessons memory — Mira's persistent, agent-curated learning store.

The agent reads the (small) lessons file in context and decides, per observation,
whether it REINFORCES an existing lesson or is NEW. This module does only the
deterministic bookkeeping on those decisions — no RAG, no embeddings, no LLM here.
A recurring lesson's `occurrences` increments instead of duplicating, so "this
happened again" compounds over time; lessons not reinforced for a while retire.

Persisted to logs/mira_lessons.json: {"lessons": [Lesson, ...], "updated_at": ...}.
"""
import json
import os
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field

VALID_CATEGORIES = {"equity-trend", "options-structure", "regime", "risk", "execution", "other"}


class Lesson(BaseModel):
    id: str
    text: str
    category: str = "other"
    first_seen: str            # ISO date
    last_seen: str             # ISO date
    occurrences: int = 1
    evidence: list[str] = Field(default_factory=list)
    status: str = "active"     # active | retired


def load_lessons(path: str) -> list[Lesson]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [Lesson(**l) for l in data.get("lessons", [])]


def save_lessons(path: str, lessons: list[Lesson]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "lessons": [l.model_dump() for l in lessons],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _next_id(existing: list[Lesson]) -> int:
    nums = []
    for l in existing:
        try:
            nums.append(int(l.id.split("-")[-1]))
        except (ValueError, IndexError):
            pass
    return (max(nums) + 1) if nums else 1


def _norm_category(c: str | None) -> str:
    c = (c or "other").strip().lower()
    return c if c in VALID_CATEGORIES else "other"


def apply_curation(existing: list[Lesson], decisions: list[dict], today: str) -> tuple[list[Lesson], list[str]]:
    """Fold the agent's curation decisions into the lessons set.

    decisions: list of {reinforce: <id>, evidence: str} OR {new: {text, category}, evidence: str}.
    An unknown/garbled reinforce id is safely treated as a NEW lesson.
    Returns (updated_lessons, reinforced_ids).
    """
    by_id = {l.id: l for l in existing}
    reinforced: list[str] = []
    next_n = _next_id(existing)

    for d in decisions or []:
        ev = (d.get("evidence") or "").strip()
        rid = d.get("reinforce")
        if rid and rid in by_id:
            lz = by_id[rid]
            lz.occurrences += 1
            lz.last_seen = today
            if ev and ev not in lz.evidence:
                lz.evidence = (lz.evidence + [ev])[-5:]   # keep last 5
            if lz.status == "retired":
                lz.status = "active"                       # reactivate on recurrence
            reinforced.append(rid)
            continue

        # new (or unknown-id fallback)
        new = d.get("new") or {}
        text = (new.get("text") or (d.get("text") if not rid else "") or "").strip()
        if not text:
            continue
        lid = f"L-{next_n:03d}"
        next_n += 1
        by_id[lid] = Lesson(
            id=lid, text=text, category=_norm_category(new.get("category")),
            first_seen=today, last_seen=today, occurrences=1,
            evidence=[ev] if ev else [], status="active",
        )

    # preserve original order, then any appended new ones
    ordered = [by_id[l.id] for l in existing] + [l for lid, l in by_id.items() if lid not in {e.id for e in existing}]
    return ordered, reinforced


def decay(lessons: list[Lesson], today: str, stale_days: int = 30) -> list[Lesson]:
    """Retire active lessons not reinforced within stale_days (kept for history)."""
    t = date.fromisoformat(today)
    for l in lessons:
        if l.status != "active":
            continue
        try:
            age = (t - date.fromisoformat(l.last_seen)).days
        except ValueError:
            continue
        if age > stale_days:
            l.status = "retired"
    return lessons


def active(lessons: list[Lesson]) -> list[Lesson]:
    return [l for l in lessons if l.status == "active"]
