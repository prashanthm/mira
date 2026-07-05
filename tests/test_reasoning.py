"""Tests for ReAct reasoning loop bounds and HITL gate (ADR-013)."""

from __future__ import annotations

from mira.orchestration.reasoning import BoundExceeded, ReasoningBudget, ReasoningLoop


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _run_until_bound(*, invoke: dict[str, object] | None = None, **budget_kwargs: object) -> BoundExceeded:
    clock = FakeClock()
    budget = ReasoningBudget(**budget_kwargs, _clock=clock)  # type: ignore[arg-type]
    loop = ReasoningLoop(budget)
    payload: dict[str, object] = {
        "query": "bounds",
        "max_iterations": 50,
        "step_tokens": 1,
        "step_cost": 0.01,
    }
    if invoke:
        payload.update(invoke)
    result = loop.invoke(payload, thread_id="bound-test")
    assert result.get("bound_exceeded"), result
    return BoundExceeded(**result["bound_exceeded"])


def test_plan_step_events_emitted_for_each_phase() -> None:
    budget = ReasoningBudget(max_steps=20)
    loop = ReasoningLoop(budget)
    result = loop.invoke({"query": "demo", "max_iterations": 1}, thread_id="steps")
    phases = [step["phase"] for step in result["plan_steps"]]
    assert phases == ["plan", "act", "observe", "reflect"]


def test_step_bound_trips_with_structured_outcome() -> None:
    exceeded = _run_until_bound(max_steps=2)
    assert exceeded.kind == "steps"
    assert exceeded.limit == 2


def test_token_bound_trips_with_structured_outcome() -> None:
    exceeded = _run_until_bound(max_steps=50, max_tokens=3)
    assert exceeded.kind == "tokens"
    assert exceeded.observed >= exceeded.limit


def test_time_bound_trips_with_structured_outcome() -> None:
    clock = FakeClock()
    budget = ReasoningBudget(max_steps=50, max_seconds=0.0, _clock=clock)
    loop = ReasoningLoop(budget)
    result = loop.invoke({"query": "time", "max_iterations": 50}, thread_id="time")
    exceeded = BoundExceeded(**result["bound_exceeded"])
    assert exceeded.kind == "time"


def test_cost_bound_trips_with_structured_outcome() -> None:
    exceeded = _run_until_bound(max_steps=50, max_cost=0.02)
    assert exceeded.kind == "cost"


def test_step_counts_one_per_iteration_not_per_node() -> None:
    # M1: a full plan→act→observe→reflect cycle consumes exactly one step.
    budget = ReasoningBudget(max_steps=20)
    loop = ReasoningLoop(budget)
    loop.invoke({"query": "x", "max_iterations": 3}, thread_id="step-count")
    assert budget.steps == 3


def test_recursion_limit_trips_langgraph_backstop() -> None:
    # L2: an explicit tiny recursion_limit stops the graph even when the
    # ReasoningBudget step ceiling is high.
    import pytest
    from langgraph.errors import GraphRecursionError

    budget = ReasoningBudget(max_steps=1000)
    loop = ReasoningLoop(budget, recursion_limit=3)
    with pytest.raises(GraphRecursionError):
        loop.invoke({"query": "loop", "max_iterations": 1000}, thread_id="recursion")


def test_hitl_gate_pauses_and_resumes() -> None:
    budget = ReasoningBudget(max_steps=20)
    loop = ReasoningLoop(budget)
    paused = loop.invoke(
        {"query": "risky", "max_iterations": 1, "require_hitl": True},
        thread_id="hitl",
    )
    assert ReasoningLoop.is_paused(paused)
    assert any(step["phase"] == "plan" for step in paused["plan_steps"])

    finished = loop.resume("approved", thread_id="hitl")
    assert finished["approval"] == "approved"
    assert any(step["phase"] == "hitl" for step in finished["plan_steps"])
    assert not ReasoningLoop.is_paused(finished)
