"""Tests for dynamic workflow composition (ADR-015)."""

from __future__ import annotations

import json
from pathlib import Path

from mira.orchestration.composition import ComposedWorkflow, WorkflowComposer, WorkflowStep
from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.specialists.finance import REPRESENTATIVE_FINANCE_QUERY
from mira.orchestration.specialists.research import REPRESENTATIVE_RESEARCH_QUERY
from mira.orchestration.supervisor import Supervisor
from mira.tools.skills import SkillsRegistry

FIXTURES = Path(__file__).parent / "fixtures"

SEQUENTIAL_QUERY = (
    f"{REPRESENTATIVE_RESEARCH_QUERY} and then {REPRESENTATIVE_FINANCE_QUERY}"
)
PARALLEL_QUERY = (
    "Compare the handbook middleware docs with the total travel spend for 2026-03"
)


def _composer() -> WorkflowComposer:
    registry = build_demo_registry(
        str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv")
    )
    return WorkflowComposer(registry, Supervisor(registry), skills=SkillsRegistry())


def test_compose_single_domain_query_is_one_step():
    steps = _composer().compose(REPRESENTATIVE_FINANCE_QUERY)
    assert len(steps) == 1
    assert steps[0].domain == "finance"
    assert steps[0].query == REPRESENTATIVE_FINANCE_QUERY


def test_compose_splits_on_and_then_seam():
    steps = _composer().compose(SEQUENTIAL_QUERY)
    assert [s.domain for s in steps] == ["research", "finance"]
    assert steps[0].query == REPRESENTATIVE_RESEARCH_QUERY
    assert steps[1].query == REPRESENTATIVE_FINANCE_QUERY


def test_compose_splits_on_semicolon_seam():
    steps = _composer().compose(
        f"{REPRESENTATIVE_RESEARCH_QUERY}; {REPRESENTATIVE_FINANCE_QUERY}"
    )
    assert [s.domain for s in steps] == ["research", "finance"]


def test_compose_keeps_unmatched_subquery_as_fallback_step():
    steps = _composer().compose(
        f"do something unrelated; {REPRESENTATIVE_FINANCE_QUERY}"
    )
    assert [s.domain for s in steps] == ["", "finance"]
    assert "fallback" in steps[0].rationale


def test_compose_fans_out_seamless_multi_card_match():
    steps = _composer().compose(PARALLEL_QUERY)
    assert [s.domain for s in steps] == ["research", "finance"]
    # Parallel shape: every step carries the whole query.
    assert all(s.query == PARALLEL_QUERY for s in steps)
    assert all("parallel fan-out" in s.rationale for s in steps)


def test_compose_is_deterministic():
    composer = _composer()
    assert composer.compose(SEQUENTIAL_QUERY) == composer.compose(SEQUENTIAL_QUERY)


def test_execute_single_domain_delegates_to_supervisor():
    workflow = _composer().execute(REPRESENTATIVE_FINANCE_QUERY, thread_id="wf-single")
    assert isinstance(workflow, ComposedWorkflow)
    assert len(workflow.steps) == 1
    assert workflow.results[0]["answer"]["total"] == 1336.40
    assert "[finance]" in workflow.synthesis


def test_execute_unmatched_single_query_falls_back_to_general():
    workflow = _composer().execute("completely unrelated question", thread_id="wf-gen")
    assert workflow.steps[0].domain == ""
    assert workflow.results == []
    assert workflow.synthesis.startswith("[general] no specialist matched")


def test_execute_sequential_pipes_steps_in_order():
    workflow = _composer().execute(SEQUENTIAL_QUERY, thread_id="wf-seq")

    assert [r["domain"] for r in workflow.results] == ["research", "finance"]
    assert workflow.results[0]["answer"]["anchor"] == "middleware-ordering"
    assert workflow.results[1]["answer"]["total"] == 1336.40
    # Prior step's attributed line travels as context into the next sub-query.
    assert "[context] [research]" in workflow.results[1]["query"]
    assert "[research]" in workflow.synthesis and "[finance]" in workflow.synthesis


def test_execute_sequential_keeps_fallback_steps_visible():
    workflow = _composer().execute(
        f"do something unrelated; {REPRESENTATIVE_FINANCE_QUERY}", thread_id="wf-fb"
    )
    assert [r["domain"] for r in workflow.results] == ["general", "finance"]
    assert workflow.results[0]["answer"]["detail"].startswith("no specialist matched")
    assert workflow.results[1]["answer"]["total"] == 1336.40
    assert "[general]" in workflow.synthesis


def test_execute_parallel_uses_supervisor_fan_out():
    workflow = _composer().execute(PARALLEL_QUERY, thread_id="wf-par")

    assert [r["domain"] for r in workflow.results] == ["research", "finance"]
    assert workflow.results[0]["answer"]["anchor"] == "middleware-ordering"
    assert workflow.results[1]["answer"]["total"] == 1336.40
    assert "[research]" in workflow.synthesis and "[finance]" in workflow.synthesis


def test_composed_workflow_serializes():
    workflow = _composer().execute(SEQUENTIAL_QUERY, thread_id="wf-json")
    payload = workflow.to_dict()
    assert json.dumps(payload)
    assert payload["steps"][0]["domain"] == "research"
    assert payload["synthesis"] == workflow.synthesis


def test_workflow_step_is_frozen():
    step = WorkflowStep(domain="finance", query="q", rationale="r")
    try:
        step.domain = "other"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("WorkflowStep must be immutable")
