"""Tests for the internals ⇄ contracts bridge (ADR-049/050)."""

from __future__ import annotations

import pytest

from mira_contracts.envelope import BudgetSpec, validate_envelope
from mira_contracts.trace import validate_trace

from mira.orchestration.contracts_bridge import (
    budget_consumed_from_reasoning,
    budget_spec_from_reasoning,
    envelope_for_dispatch,
    reasoning_budget_from_spec,
    specialist_result_from_trace,
    trace_from_specialist_result,
)
from mira.orchestration.reasoning import ReasoningBudget
from mira.orchestration.specialist_scaffold import DomainSpec, SpecialistResult

GROUNDED_ANSWER = {
    "anchor": "middleware-ordering",
    "provenance": {"source_type": "docs.section", "source_id": "handbook.md#middleware"},
}
PLAN_STEPS = [
    {"event": "plan_step", "phase": "plan", "detail": "plan-1:q", "index": 0},
    {"event": "plan_step", "phase": "act", "detail": "act:plan-1:q", "index": 1},
    {"event": "plan_step", "phase": "observe", "detail": "obs", "index": 2},
]


def _ok_result() -> SpecialistResult:
    return SpecialistResult(
        domain="research",
        query="what about middleware?",
        answer=dict(GROUNDED_ANSWER),
        plan_steps=[dict(step) for step in PLAN_STEPS],
    )


@pytest.mark.parametrize(
    "result",
    [
        _ok_result(),
        SpecialistResult(domain="research", query="q", answer={}, error="no tools allowed"),
        SpecialistResult(
            domain="finance",
            query="q",
            answer={},
            plan_steps=[dict(PLAN_STEPS[0])],
            bound_exceeded={"kind": "steps", "limit": 1.0, "observed": 1.0, "message": "stop"},
        ),
    ],
    ids=["ok", "error", "bound-exceeded"],
)
def test_specialist_result_round_trip_is_byte_equal(result):
    trace = trace_from_specialist_result(result, task_id="t1", correlation_id="c1")
    validate_trace(trace)  # every bridged trace is contract-valid
    back = specialist_result_from_trace(trace, query=result.query)
    assert back.to_dict() == result.to_dict()


def test_trace_status_reflects_result_state():
    ok = trace_from_specialist_result(_ok_result(), task_id="t")
    err = trace_from_specialist_result(
        SpecialistResult(domain="d", query="q", answer={}, error="boom"), task_id="t"
    )
    bound = trace_from_specialist_result(
        SpecialistResult(
            domain="d",
            query="q",
            answer={},
            bound_exceeded={"kind": "steps", "limit": 0, "observed": 0, "message": "m"},
        ),
        task_id="t",
    )
    assert (ok.status, err.status, bound.status) == ("ok", "error", "bound_exceeded")
    assert ok.agent.kind == "specialist" and ok.agent.name == "research"


def test_budget_spec_round_trip_preserves_ceilings():
    budget = ReasoningBudget(max_steps=3, max_tokens=50, max_seconds=7.5, max_cost=0.25)
    spec = budget_spec_from_reasoning(budget)
    rebuilt = reasoning_budget_from_spec(spec)
    assert (rebuilt.max_steps, rebuilt.max_tokens, rebuilt.max_seconds, rebuilt.max_cost) == (
        3,
        50,
        7.5,
        0.25,
    )
    assert (rebuilt.steps, rebuilt.tokens, rebuilt.cost) == (0, 0, 0.0)


def test_default_budget_spec_matches_reasoning_defaults():
    assert budget_spec_from_reasoning(ReasoningBudget()) == BudgetSpec()


def test_budget_consumed_snapshot():
    budget = ReasoningBudget(max_steps=5)
    budget.record_step(tokens=3, cost=0.1)
    budget.record_usage(tokens=2)
    consumed = budget_consumed_from_reasoning(budget)
    assert (consumed.steps, consumed.tokens, consumed.cost) == (1, 5, 0.1)


def test_envelope_for_dispatch_is_contract_valid_and_fail_closed():
    spec = DomainSpec(domain_id="research", tool_prefixes=frozenset({"docs."}))
    envelope = envelope_for_dispatch(
        "what about middleware?",
        spec,
        task_id="research:golden-1",
        require_hitl=True,
        max_iterations=2,
        entitlements={"docs.": "connector:docs:read"},
    )
    validate_envelope(envelope)
    assert envelope.objective == "what about middleware?"
    assert envelope.constraints.require_hitl and envelope.constraints.max_iterations == 2
    assert [(g.name_prefix, g.entitlement) for g in envelope.tool_grants] == [
        ("docs.", "connector:docs:read")
    ]

    # No prefixes ⇒ no grants (fail-closed default, matching the scaffold).
    bare = envelope_for_dispatch(
        "q", DomainSpec(domain_id="none", tool_prefixes=frozenset()), task_id="t"
    )
    assert bare.tool_grants == ()
    # Unlisted prefixes get the declarative default entitlement.
    default = envelope_for_dispatch(
        "q", DomainSpec(domain_id="x", tool_prefixes=frozenset({"ledger."})), task_id="t"
    )
    assert default.tool_grants[0].entitlement == "tool:ledger"
