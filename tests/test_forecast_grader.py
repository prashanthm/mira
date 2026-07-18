"""The forecast-grader specialist (Replay Forecast grading, offline fakes).

Binds the grader to the fake ``vantage.replay_forecasts`` tool (a graded-run
bundle with CODE-computed scores) and asserts the anti-reward-hacking
invariants: the grader ECHOES the scores it is given (never computes them), it
can reach ONLY the read-only vantage surface, and the forecasting analyst's
snapshot never carries the calibration memory (so there is no feedback path to
game).
"""

from __future__ import annotations

from typing import Any

from mira.orchestration.reasoning import ReasoningLoop
from mira.orchestration.specialist_scaffold import (
    SpecialistSubgraph,
    filter_tools_by_domain,
)
from mira.orchestration.specialists.domains import FINANCE_DOMAIN, RESEARCH_DOMAIN
from mira.orchestration.specialists.forecast_grader import (
    FORECAST_GRADER_CARD,
    FORECAST_GRADER_DOMAIN,
    REPRESENTATIVE_GRADE_QUERY,
    build_forecast_grader_specialist,
    forecast_grader_registry_entry,
)
from mira.orchestration.specialists.forecast_grader import _infer_grade_bundle

from tests.fake_vantage import (
    REPLAY_FORECASTS_RESULT,
    fake_vantage_registered_tools,
)


def _grader_with_calls() -> tuple[SpecialistSubgraph, list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    grader = build_forecast_grader_specialist(fake_vantage_registered_tools(calls=calls))
    return grader, calls


def _registry_map(tools):
    return {t.contract.name: t for t in tools}


# ── scaffold identity ────────────────────────────────────────────────────────

def test_grader_is_reasoning_subgraph() -> None:
    grader, _ = _grader_with_calls()
    assert isinstance(grader, SpecialistSubgraph)
    assert isinstance(grader.reasoning_loop, ReasoningLoop)
    assert grader.domain_spec.domain_id == "forecast_grader"
    assert grader.domain_spec.tool_prefixes == frozenset({"vantage."})


# ── ref inference fetches the run bundle ─────────────────────────────────────

def test_ref_line_fetches_replay_forecasts_tool() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    tools = fake_vantage_registered_tools(calls=calls)
    bundle = _infer_grade_bundle(
        "FORECAST_GRADE_REF run_id=rf-SPX-2026-07-16-demo", _registry_map(tools))
    assert bundle is not None
    assert ("vantage.replay_forecasts", {"run_id": "rf-SPX-2026-07-16-demo"}) in calls
    # the tool returns the graded bundle + a ready-made prompt
    assert bundle["bundle"]["run_id"] == "rf-SPX-2026-07-16-demo"
    assert "prompt" in bundle


def test_no_ref_line_infers_nothing() -> None:
    tools = fake_vantage_registered_tools()
    assert _infer_grade_bundle("grade my run", _registry_map(tools)) is None


# ── ECHO-NOT-COMPUTE: the scores come from code, the grader reads them ───────

def test_bundle_carries_code_computed_scores_the_grader_reads() -> None:
    tools = fake_vantage_registered_tools()
    out = _infer_grade_bundle(
        "FORECAST_GRADE_REF run_id=rf-SPX-2026-07-16-demo", _registry_map(tools))
    scores = out["bundle"]["scores"]
    # the numbers are already resolved in the bundle — nothing for the LLM to compute
    assert scores["overall"]["hit_rate"] == 0.667
    assert scores["overall"]["wins"] == 4
    # provenance gating is present in the DATA, not left to the model
    assert scores["by_time"]["midday (11:00-14:00)"]["insufficient"] is True
    # the grader's hint forbids inventing scores
    hint = FORECAST_GRADER_CARD.synthesis_hint.lower()
    assert "never compute, alter, or invent" in hint
    assert "insufficient sample" in hint


def test_grade_prompt_instructs_read_not_compute() -> None:
    prompt = REPLAY_FORECASTS_RESULT["prompt"].lower()
    assert "already computed" in prompt
    assert "never compute" in prompt


# ── isolation: the grader can reach ONLY the read-only vantage surface ───────

def test_grader_tools_are_vantage_only() -> None:
    tools = fake_vantage_registered_tools()
    # every tool the grader can see is a read-only vantage tool
    visible = filter_tools_by_domain(tools, FORECAST_GRADER_DOMAIN)
    assert visible, "the grader must see the vantage surface"
    assert all(t.contract.name.startswith("vantage.") for t in visible)
    assert all(t.contract.readOnlyHint for t in visible)
    # and NONE of the non-vantage domains can see these tools
    assert filter_tools_by_domain(tools, RESEARCH_DOMAIN) == []
    assert filter_tools_by_domain(tools, FINANCE_DOMAIN) == []


# ── anti-reward-hacking: the analyst never sees the grades ───────────────────

def test_calibration_memory_is_absent_from_the_analyst_snapshot() -> None:
    """The forecast-analyst reasons over vantage.spx_snapshot; that payload must carry
    NO calibration / hit-rate — the grader's memory is grader-owned and read-only,
    so the forecaster can't be tuned toward its own grades."""
    from tests.fake_vantage import RESULTS
    snap = RESULTS.get("vantage.spx_snapshot")
    # the snapshot tool isn't a grading surface; if present it must be clean
    if snap is not None:
        text = str(snap).lower()
        assert "hit_rate" not in text
        assert "calibration" not in text


# ── end-to-end grounded contract ─────────────────────────────────────────────

def test_representative_query_returns_grounded_contract() -> None:
    card, factory = forecast_grader_registry_entry(fake_vantage_registered_tools())
    grader = factory()
    result = grader.invoke(
        REPRESENTATIVE_GRADE_QUERY + " FORECAST_GRADE_REF run_id=rf-SPX-2026-07-16-demo",
        thread_id="live")
    assert result.answer["provenance"]["source_type"] == "vantage"
