import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mira import insight
from mira.schema import InsightReport


def test_extract_fenced_json():
    text = 'Here is the report:\n```json\n{"summary": "hi", "confidence": "low"}\n```\nDone.'
    data = insight._extract_json(text)
    assert data["summary"] == "hi"


def test_extract_bare_json():
    text = 'prose {"summary": "x", "adjustments": ["a"]} trailing'
    data = insight._extract_json(text)
    assert data["adjustments"] == ["a"]


def test_coerce_valid():
    rep = insight._coerce_report({"summary": "s", "confidence": "high"}, "")
    assert isinstance(rep, InsightReport)
    assert rep.confidence == "high"


def test_coerce_falls_back_to_raw():
    # model returned no usable JSON → wrap the raw text, never throw
    rep = insight._coerce_report(None, "free-form analysis text")
    assert "free-form" in rep.summary
    assert rep.confidence == "low"
