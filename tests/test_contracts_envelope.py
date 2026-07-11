"""Tests for mira_contracts.envelope (ADR-049)."""

from __future__ import annotations

import pytest

from mira_contracts.envelope import (
    ENVELOPE_VERSION,
    BudgetSpec,
    Constraints,
    ContextRef,
    ContractViolation,
    ExecutionEnvelope,
    SuccessCriterion,
    ToolGrant,
    validate_envelope,
)


def _full_envelope() -> ExecutionEnvelope:
    return ExecutionEnvelope(
        task_id="research:golden-1",
        objective="What does the handbook say about middleware ordering?",
        correlation_id="corr-1",
        tenant="acme",
        context_refs=(ContextRef(kind="doc", id="handbook.md", description="corpus"),),
        constraints=Constraints(require_hitl=True, max_iterations=2, disallowed=("x",)),
        tool_grants=(ToolGrant(name_prefix="docs.", entitlement="connector:docs:read"),),
        budget=BudgetSpec(max_steps=5, max_tokens=100, max_seconds=10.0, max_cost=0.5),
        success_criteria=(
            SuccessCriterion(kind="answer_field", key="anchor", expected="middleware-ordering"),
            SuccessCriterion(kind="grounded"),
            SuccessCriterion(kind="min_trace_score", threshold=1.0),
        ),
    )


def test_round_trip_full_envelope():
    envelope = _full_envelope()
    assert ExecutionEnvelope.from_dict(envelope.to_dict()) == envelope


def test_round_trip_minimal_envelope():
    envelope = ExecutionEnvelope(task_id="t1", objective="do the thing")
    assert ExecutionEnvelope.from_dict(envelope.to_dict()) == envelope
    assert envelope.envelope_version == ENVELOPE_VERSION
    assert envelope.tool_grants == ()  # fail-closed default: no tools


def test_validate_accepts_full_and_minimal():
    for envelope in (_full_envelope(), ExecutionEnvelope(task_id="t1", objective="x")):
        parsed = validate_envelope(envelope.to_dict())
        assert parsed == envelope
        # dataclass input also accepted
        assert validate_envelope(envelope) == envelope


def test_budget_defaults_match_reasoning_budget_ceilings():
    budget = BudgetSpec()
    assert (budget.max_steps, budget.max_tokens, budget.max_seconds, budget.max_cost) == (
        10,
        8000,
        300.0,
        1.0,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("envelope_version"),
        lambda d: d.update(envelope_version="2"),
        lambda d: d.pop("objective"),
        lambda d: d.update(objective=""),
        lambda d: d.pop("task_id"),
        lambda d: d.update(unexpected_key=1),
        lambda d: d.update(budget={"max_steps": -1}),
        lambda d: d.update(tool_grants=[{"name_prefix": "docs."}]),
        lambda d: d.update(success_criteria=[{"kind": "unknown_kind"}]),
    ],
    ids=[
        "missing-version",
        "wrong-version",
        "missing-objective",
        "empty-objective",
        "missing-task-id",
        "extra-key",
        "negative-steps",
        "grant-without-entitlement",
        "unknown-criterion-kind",
    ],
)
def test_validation_is_fail_closed(mutate):
    doc = _full_envelope().to_dict()
    mutate(doc)
    with pytest.raises(ContractViolation):
        validate_envelope(doc)


def test_violation_carries_all_error_details():
    doc = _full_envelope().to_dict()
    doc["tenant"] = 7
    doc["budget"] = {"max_cost": -1}
    with pytest.raises(ContractViolation) as excinfo:
        validate_envelope(doc)
    assert len(excinfo.value.details) >= 2
