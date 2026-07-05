"""ReAct reasoning loop with layered safety bounds (ADR-013)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from mira.orchestration.interrupts import annotate_graph_interrupt, is_graph_paused

ToolFn = Callable[[str], str]
ClockFn = Callable[[], float]


@dataclass(frozen=True, slots=True)
class BoundExceeded:
    """Structured outcome when a safety ceiling is hit."""

    kind: str
    limit: float
    observed: float
    message: str


@dataclass
class ReasoningBudget:
    """Tracks step, token, wall-clock, and cost consumption against ceilings."""

    max_steps: int = 10
    max_tokens: int = 8000
    max_seconds: float = 300.0
    max_cost: float = 1.0
    steps: int = 0
    tokens: int = 0
    cost: float = 0.0
    _started_at: float = field(init=False)
    _clock: ClockFn = field(default=time.monotonic, repr=False)

    def __post_init__(self) -> None:
        self._started_at = self._clock()

    def check_before_step(self) -> BoundExceeded | None:
        if self.steps >= self.max_steps:
            return BoundExceeded("steps", self.max_steps, self.steps, "step limit reached")
        if self.tokens >= self.max_tokens:
            return BoundExceeded("tokens", self.max_tokens, self.tokens, "token limit reached")
        elapsed = self._clock() - self._started_at
        if elapsed >= self.max_seconds:
            return BoundExceeded("time", self.max_seconds, elapsed, "time limit reached")
        if self.cost >= self.max_cost:
            return BoundExceeded("cost", self.max_cost, self.cost, "cost limit reached")
        return None

    def record_step(self, *, tokens: int = 0, cost: float = 0.0) -> None:
        """Count one ReAct *iteration* (ADR-013 step semantics) and accrue usage.

        Call exactly once per plan→act→observe→reflect cycle (from ``plan``), not
        per graph node, so ``max_steps`` bounds iterations rather than nodes.
        """
        self.steps += 1
        self.tokens += tokens
        self.cost += cost

    def record_usage(self, *, tokens: int = 0, cost: float = 0.0) -> None:
        """Accrue token/cost for a non-iteration phase without consuming a step."""
        self.tokens += tokens
        self.cost += cost


class ReasoningState(TypedDict, total=False):
    query: str
    iteration: int
    plan: str
    action: str
    observation: str
    reflection: str
    plan_steps: list[dict[str, Any]]
    bound_exceeded: dict[str, Any]
    finished: bool
    require_hitl: bool
    approval: str
    step_tokens: int
    step_cost: float
    max_iterations: int


def _emit(state: ReasoningState, phase: str, detail: str) -> list[dict[str, Any]]:
    steps = list(state.get("plan_steps") or [])
    steps.append({"event": "plan_step", "phase": phase, "detail": detail, "index": len(steps)})
    return steps


def _bound_patch(budget: ReasoningBudget) -> dict[str, Any] | None:
    exceeded = budget.check_before_step()
    if exceeded is None:
        return None
    return {"bound_exceeded": asdict(exceeded), "finished": True}


class ReasoningLoop:
    """ReAct graph: plan → act → observe → reflect, with optional HITL interrupt gate."""

    def __init__(
        self,
        budget: ReasoningBudget,
        *,
        tool_fn: ToolFn | None = None,
        recursion_limit: int | None = None,
    ) -> None:
        self._budget = budget
        self._tool_fn = tool_fn or (lambda action: f"observed:{action}")
        # recursion_limit is LangGraph's node-level backstop. Each ReAct iteration
        # is ~4 nodes (plan/act/observe/reflect) plus a small fixed overhead for the
        # HITL gate and terminal routing; ReasoningBudget.max_steps now bounds
        # *iterations*, so derive the node backstop from iterations × 4 + overhead.
        self._recursion_limit = (
            recursion_limit if recursion_limit is not None else max(budget.max_steps * 4 + 4, 8)
        )
        self._app = self._build_graph().compile(checkpointer=InMemorySaver())

    def _build_graph(self) -> StateGraph:
        budget = self._budget
        tool_fn = self._tool_fn

        def plan(state: ReasoningState) -> dict[str, Any]:
            if patch := _bound_patch(budget):
                return patch
            iteration = int(state.get("iteration") or 0) + 1
            query = state.get("query", "")
            plan_text = f"plan-{iteration}:{query}"
            budget.record_step(
                tokens=int(state.get("step_tokens") or 1),
                cost=float(state.get("step_cost") or 0.0),
            )
            return {
                "iteration": iteration,
                "plan": plan_text,
                "plan_steps": _emit(state, "plan", plan_text),
            }

        def act(state: ReasoningState) -> dict[str, Any]:
            if patch := _bound_patch(budget):
                return patch
            action = f"act:{state.get('plan', '')}"
            budget.record_usage(
                tokens=int(state.get("step_tokens") or 1),
                cost=float(state.get("step_cost") or 0.0),
            )
            return {"action": action, "plan_steps": _emit(state, "act", action)}

        def observe(state: ReasoningState) -> dict[str, Any]:
            if patch := _bound_patch(budget):
                return patch
            observation = tool_fn(state.get("action", ""))
            budget.record_usage(
                tokens=int(state.get("step_tokens") or 1),
                cost=float(state.get("step_cost") or 0.0),
            )
            return {
                "observation": observation,
                "plan_steps": _emit(state, "observe", observation),
            }

        def reflect(state: ReasoningState) -> dict[str, Any]:
            if patch := _bound_patch(budget):
                return patch
            iteration = int(state.get("iteration") or 0)
            max_iterations = int(state.get("max_iterations") or 1)
            reflection = f"reflect:{iteration}"
            budget.record_usage(
                tokens=int(state.get("step_tokens") or 1),
                cost=float(state.get("step_cost") or 0.0),
            )
            finished = iteration >= max_iterations
            return {
                "reflection": reflection,
                "finished": finished,
                "plan_steps": _emit(state, "reflect", reflection),
            }

        # NOTE (M2, deferred): ADR-013 places the interrupt() gate *before*
        # irreversible/escalated actions (pre-act). This Phase-1 gate runs after a
        # completed iteration because there is no action-risk classifier yet; once
        # risk scoring lands, route high-risk paths through hitl_gate before `act`.
        # L1: token/cost bounds read step_tokens/step_cost from graph state; in
        # production these move to the model gateway's attribution (ADR-010/042).
        def hitl_gate(state: ReasoningState) -> dict[str, Any]:
            approval = interrupt({"action": state.get("action", "")})
            return {
                "approval": str(approval),
                "plan_steps": _emit(state, "hitl", str(approval)),
            }

        def route_after_reflect(state: ReasoningState) -> str:
            if state.get("bound_exceeded"):
                return END
            if state.get("finished"):
                return "hitl_gate" if state.get("require_hitl") else END
            return "plan_phase"

        def route_after_hitl(_: ReasoningState) -> str:
            return END

        graph = StateGraph(ReasoningState)
        # Node names must not collide with state keys (LangGraph 0.3.x).
        graph.add_node("plan_phase", plan)
        graph.add_node("act", act)
        graph.add_node("observe", observe)
        graph.add_node("reflect", reflect)
        graph.add_node("hitl_gate", hitl_gate)
        graph.add_edge(START, "plan_phase")
        graph.add_edge("plan_phase", "act")
        graph.add_edge("act", "observe")
        graph.add_edge("observe", "reflect")
        graph.add_conditional_edges(
            "reflect", route_after_reflect, ["plan_phase", "hitl_gate", END]
        )
        graph.add_conditional_edges("hitl_gate", route_after_hitl, [END])
        return graph

    def invoke(
        self,
        state: ReasoningState | Mapping[str, Any],
        *,
        thread_id: str,
    ) -> dict[str, Any]:
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._recursion_limit,
        }
        result = self._app.invoke(dict(state), config)
        return annotate_graph_interrupt(self._app, result, config)

    def resume(self, value: Any, *, thread_id: str) -> dict[str, Any]:
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._recursion_limit,
        }
        result = self._app.invoke(Command(resume=value), config)
        return annotate_graph_interrupt(self._app, result, config)

    @staticmethod
    def is_paused(result: Mapping[str, Any]) -> bool:
        return is_graph_paused(result)
