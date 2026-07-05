"""Tests for the trace-scoring harness (ADR-045)."""

from __future__ import annotations

from evals.trace_scoring import TraceScore, score_run, score_trace


def _good_result() -> dict:
    return {
        "domain": "research",
        "query": "q",
        "answer": {
            "anchor": "middleware-ordering",
            "provenance": {"source_type": "docs", "source_id": "handbook#middleware-ordering"},
        },
        "plan_steps": [{"event": "plan_step", "phase": "plan"}],
        "bound_exceeded": None,
        "error": None,
    }


def test_perfect_trace_scores_one():
    score = score_trace(_good_result())
    assert score == TraceScore(has_plan=True, grounded=True, within_bounds=True, error_free=True)
    assert score.score == 1.0


def test_missing_plan_lowers_score():
    result = _good_result() | {"plan_steps": []}
    score = score_trace(result)
    assert not score.has_plan
    assert score.score == 0.75


def test_ungrounded_answer_detected():
    result = _good_result() | {"answer": {"value": 42}}  # no provenance anywhere
    assert not score_trace(result).grounded


def test_nested_provenance_counts_as_grounded():
    result = _good_result() | {
        "answer": {"summary": {"provenance": {"source_type": "ledger", "source_id": "l1"}}}
    }
    assert score_trace(result).grounded


def test_bound_exceeded_and_error_flagged():
    result = _good_result() | {
        "bound_exceeded": {"kind": "steps"},
        "error": "boom",
    }
    score = score_trace(result)
    assert not score.within_bounds
    assert not score.error_free
    assert score.score == 0.5


def test_score_run_aggregates_dimensions():
    results = [_good_result(), _good_result() | {"plan_steps": []}]
    run = score_run(results)
    assert run["count"] == 2
    assert run["dimensions"]["has_plan"] == 0.5
    assert run["dimensions"]["grounded"] == 1.0
    assert run["mean_score"] == (1.0 + 0.75) / 2


def test_score_run_empty_is_zero():
    run = score_run([])
    assert run["count"] == 0
    assert run["mean_score"] == 0.0
