"""Tests for the regression gate and its ADR-012 promotion wiring (ADR-045)."""

from __future__ import annotations

import json

import pytest

from mira.model.versioning import EvalGateFailed, Registry

from evals.regression_gate import eval_gate, load_golden_cases, run_gate


def test_gate_passes_on_the_shipped_golden_set():
    report = run_gate()
    assert report.total >= 6
    assert report.failures == []
    assert report.passed


def test_gate_fails_closed_on_empty_golden_set(tmp_path):
    report = run_gate(tmp_path)  # no *.jsonl files
    assert report.total == 0
    assert not report.passed


def test_gate_reports_wrong_expectation(tmp_path):
    bad = {
        "id": "bogus",
        "query": "What was the total travel spend for 2026-03?",
        "domain": "finance",
        "expect": {"total": 999.99},
    }
    (tmp_path / "bad.jsonl").write_text(json.dumps(bad) + "\n")
    report = run_gate(tmp_path)
    assert not report.passed
    assert report.failures[0]["id"] == "bogus"
    assert "answer['total']" in report.failures[0]["reason"]


def test_gate_reports_misrouted_domain(tmp_path):
    bad = {
        "id": "misrouted",
        "query": "What was the total travel spend for 2026-03?",
        "domain": "research",
        "expect": {},
    }
    (tmp_path / "bad.jsonl").write_text(json.dumps(bad) + "\n")
    report = run_gate(tmp_path)
    assert not report.passed
    assert "routed to 'finance'" in report.failures[0]["reason"]


def test_eval_gate_wires_into_versioning_promotion():
    """The gate is the ADR-012 eval_gate: staging promotion runs the golden set."""
    registry = Registry()
    registry.register("prompt:system", "v1", {"text": "hello"})
    registry.promote("prompt:system", "v1", "dev", eval_gate)
    registry.promote("prompt:system", "v1", "staging", eval_gate)  # gate runs and passes
    assert registry.resolve("prompt:system", "staging").version == "v1"


def test_failing_gate_blocks_promotion():
    registry = Registry()
    registry.register("prompt:system", "v1", {"text": "hello"})
    registry.promote("prompt:system", "v1", "dev", eval_gate)
    with pytest.raises(EvalGateFailed):
        registry.promote("prompt:system", "v1", "staging", lambda: run_gate("/nonexistent").passed)


def test_load_golden_cases_reads_all_files():
    cases = load_golden_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "golden ids must be unique"
    assert any(i.startswith("research") for i in ids)
    assert any(i.startswith("finance") for i in ids)
