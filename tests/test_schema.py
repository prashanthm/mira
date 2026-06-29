import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mira.schema import Insight, InsightReport


def test_minimal_report_valid():
    r = InsightReport(summary="ok")
    assert r.confidence == "low"
    assert r.what_worked == []


def test_full_report_round_trips():
    r = InsightReport(
        summary="s",
        what_worked=[Insight(topic="long_put", detail="graded A", evidence="6/6 A")],
        adjustments=["consider X"],
        confidence="medium",
    )
    d = r.model_dump()
    assert d["what_worked"][0]["topic"] == "long_put"
    assert InsightReport(**d).confidence == "medium"


def test_json_schema_has_fields():
    s = InsightReport.model_json_schema()
    assert {"summary", "what_worked", "what_didnt", "adjustments", "confidence"} <= set(s["properties"])
