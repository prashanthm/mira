import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mira.memory import Lesson, active, apply_curation, decay, load_lessons, save_lessons


def _seed():
    return [Lesson(id="L-001", text="bearish into a rally stops out", category="equity-trend",
                   first_seen="2026-06-01", last_seen="2026-06-01", occurrences=1)]


def test_reinforce_increments_and_updates():
    lessons, reinforced = apply_curation(_seed(), [{"reinforce": "L-001", "evidence": "3 stops -33.18"}], "2026-06-29")
    assert reinforced == ["L-001"]
    l = lessons[0]
    assert l.occurrences == 2
    assert l.last_seen == "2026-06-29"
    assert "3 stops -33.18" in l.evidence


def test_new_lesson_appended_and_stamped():
    lessons, reinforced = apply_curation(_seed(), [{"new": {"text": "QQQ stops fastest", "category": "execution"}, "evidence": "QQQ -5.39"}], "2026-06-29")
    assert reinforced == []
    new = [l for l in lessons if l.text == "QQQ stops fastest"][0]
    assert new.id == "L-002"
    assert new.occurrences == 1
    assert new.first_seen == new.last_seen == "2026-06-29"
    assert new.category == "execution"


def test_unknown_reinforce_id_becomes_new():
    lessons, reinforced = apply_curation(_seed(), [{"reinforce": "L-999", "new": {"text": "novel thing"}, "evidence": "x"}], "2026-06-29")
    assert reinforced == []  # unknown id not counted as a reinforce
    assert any(l.text == "novel thing" for l in lessons)


def test_invalid_category_falls_back_to_other():
    lessons, _ = apply_curation([], [{"new": {"text": "t", "category": "bogus"}}], "2026-06-29")
    assert lessons[0].category == "other"


def test_decay_retires_stale_keeps_recent():
    lessons = [
        Lesson(id="L-001", text="old", first_seen="2026-01-01", last_seen="2026-01-01", occurrences=1),
        Lesson(id="L-002", text="fresh", first_seen="2026-06-20", last_seen="2026-06-28", occurrences=3),
    ]
    decay(lessons, today="2026-06-29", stale_days=30)
    assert lessons[0].status == "retired"
    assert lessons[1].status == "active"
    assert [l.id for l in active(lessons)] == ["L-002"]


def test_reinforce_reactivates_retired():
    l = Lesson(id="L-001", text="x", first_seen="2026-01-01", last_seen="2026-01-01", occurrences=1, status="retired")
    lessons, reinforced = apply_curation([l], [{"reinforce": "L-001", "evidence": "back again"}], "2026-06-29")
    assert lessons[0].status == "active"
    assert lessons[0].occurrences == 2


def test_save_load_roundtrip(tmp_path):
    p = str(tmp_path / "lessons.json")
    save_lessons(p, _seed())
    back = load_lessons(p)
    assert back[0].id == "L-001"
    assert load_lessons(str(tmp_path / "nope.json")) == []
