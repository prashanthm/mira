"""Tests for the ADR-051 stub foreign agent."""

from __future__ import annotations

import ast
import inspect

import mira_harness.stub_agent as stub_module
from mira_contracts.agent import EnvelopeRunner
from mira_contracts.envelope import BudgetSpec, ExecutionEnvelope
from mira_contracts.trace import validate_trace
from mira_harness.scoring import score_trace
from mira_harness.stub_agent import AGENT_NAME, SOURCE_TYPE, StubEchoAgent


def _envelope(objective: str, **kwargs) -> ExecutionEnvelope:
    return ExecutionEnvelope(task_id="t1", objective=objective, **kwargs)


def test_stub_imports_contracts_only():
    """The agent-agnosticism proof (ADR-051): no mira/mira_harness coupling."""
    tree = ast.parse(inspect.getsource(stub_module))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    for module in modules:
        root = module.split(".", 1)[0]
        assert root in {"mira_contracts", "typing", "__future__"}, (
            f"stub_agent may import mira_contracts + stdlib typing only, found {module!r}"
        )


def test_stub_satisfies_envelope_runner_protocol():
    assert isinstance(StubEchoAgent(), EnvelopeRunner)


def test_card_is_a2a_shaped():
    card = StubEchoAgent().card()
    assert card["name"] == AGENT_NAME
    assert set(card) == {"name", "description", "version", "capabilities"}
    assert card["capabilities"]["tool_prefixes"] == [f"{AGENT_NAME}."]


def test_run_is_deterministic_grounded_and_contract_valid():
    agent = StubEchoAgent()
    envelope = _envelope("delegate to the external echo partner: middleware")
    first = agent.run(envelope)
    second = agent.run(envelope)
    assert first == second
    trace = validate_trace(first)
    assert trace.answer["echo"] == "middleware"
    assert trace.answer["provenance"] == {"source_type": SOURCE_TYPE, "source_id": "t1"}
    assert trace.agent.kind == "foreign"
    assert [event.phase for event in trace.events] == ["plan", "act", "observe"]
    assert trace.costs[0].self_reported and trace.costs[0].cost == 0.0
    assert trace.budget_consumed.steps == 1


def test_run_scores_structurally_perfect():
    trace = StubEchoAgent().run(_envelope("echo this: hello"))
    shaped = {
        "answer": trace.answer,
        "plan_steps": [event.to_dict() for event in trace.events],
        "bound_exceeded": trace.bound_exceeded,
        "error": None,
    }
    assert score_trace(shaped).score == 1.0


def test_echo_token_without_colon_uses_last_word():
    trace = StubEchoAgent().run(_envelope("please repeat the word Sunflower"))
    assert trace.answer["echo"] == "sunflower"


def test_zero_step_budget_returns_bound_exceeded():
    """The ADR-051 budget-conformance probe."""
    trace = StubEchoAgent().run(
        _envelope("echo: anything", budget=BudgetSpec(max_steps=0))
    )
    assert trace.status == "bound_exceeded"
    assert trace.bound_exceeded == {
        "kind": "steps",
        "limit": 0.0,
        "observed": 0.0,
        "message": "step limit reached",
    }
    assert trace.answer == {}
    validate_trace(trace)
