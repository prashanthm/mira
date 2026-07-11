"""Internals ⇄ public-contracts adapters (ADR-049/050).

The one seam where Mira's internal shapes (``ReasoningBudget``,
``SpecialistResult``, ``DomainSpec`` dispatch) translate to and from the
agent-agnostic ``mira_contracts`` documents. Internals adapt *to* the
contracts here — the contracts never grow Mira-specific fields.

Round-trip fidelity is the tested invariant:
``specialist_result_from_trace(trace_from_specialist_result(r), query=r.query)``
reproduces ``r.to_dict()`` byte-for-byte.
"""

from __future__ import annotations

from collections.abc import Mapping

from mira_contracts.envelope import (
    BudgetSpec,
    Constraints,
    ExecutionEnvelope,
    ToolGrant,
)
from mira_contracts.trace import (
    AgentRef,
    BudgetConsumed,
    Decision,
    TraceEvent,
    TraceResult,
)

from mira.orchestration.reasoning import ReasoningBudget
from mira.orchestration.specialist_scaffold import DomainSpec, SpecialistResult


def budget_spec_from_reasoning(budget: ReasoningBudget) -> BudgetSpec:
    """Project a ``ReasoningBudget``'s ceilings onto the public ``BudgetSpec``."""
    return BudgetSpec(
        max_steps=budget.max_steps,
        max_tokens=budget.max_tokens,
        max_seconds=budget.max_seconds,
        max_cost=budget.max_cost,
    )


def reasoning_budget_from_spec(spec: BudgetSpec) -> ReasoningBudget:
    """Build a fresh (zero-consumption) ``ReasoningBudget`` from public ceilings."""
    return ReasoningBudget(
        max_steps=spec.max_steps,
        max_tokens=spec.max_tokens,
        max_seconds=spec.max_seconds,
        max_cost=spec.max_cost,
    )


def budget_consumed_from_reasoning(budget: ReasoningBudget) -> BudgetConsumed:
    """Snapshot a ``ReasoningBudget``'s consumption counters (seconds excluded:
    the internal budget tracks wall-clock against its own monotonic start)."""
    return BudgetConsumed(steps=budget.steps, tokens=budget.tokens, cost=budget.cost)


def envelope_for_dispatch(
    query: str,
    spec: DomainSpec,
    *,
    task_id: str,
    budget: BudgetSpec | None = None,
    correlation_id: str = "",
    tenant: str = "",
    require_hitl: bool = False,
    max_iterations: int = 1,
    entitlements: Mapping[str, str] | None = None,
) -> ExecutionEnvelope:
    """Build the public envelope for one supervisor-style dispatch.

    ``tool_grants`` mirror the domain's allow-listed prefixes; entitlements
    come from ``entitlements`` (prefix → entitlement) when the caller knows
    the real contract values, else the declarative ``tool:<prefix>`` default.
    No prefixes ⇒ no grants — fail-closed, same as the specialist scaffold.
    """
    resolved_entitlements = dict(entitlements or {})
    grants = tuple(
        ToolGrant(
            name_prefix=prefix,
            entitlement=resolved_entitlements.get(prefix, f"tool:{prefix.rstrip('.')}"),
        )
        for prefix in sorted(spec.tool_prefixes)
    )
    return ExecutionEnvelope(
        task_id=task_id,
        objective=query,
        correlation_id=correlation_id,
        tenant=tenant,
        constraints=Constraints(require_hitl=require_hitl, max_iterations=max_iterations),
        tool_grants=grants,
        budget=budget if budget is not None else BudgetSpec(),
    )


def trace_from_specialist_result(
    result: SpecialistResult,
    *,
    task_id: str,
    correlation_id: str = "",
    agent: AgentRef | None = None,
) -> TraceResult:
    """Lift a ``SpecialistResult`` into the public trace contract.

    ``answer``/``events``/``bound_exceeded`` pass through byte-compatibly
    (ADR-049); the internal error string becomes the structured
    ``{code, message}`` shape.
    """
    if result.error:
        status = "error"
    elif result.bound_exceeded:
        status = "bound_exceeded"
    else:
        status = "ok"
    return TraceResult(
        task_id=task_id,
        correlation_id=correlation_id,
        agent=agent if agent is not None else AgentRef(name=result.domain, kind="specialist"),
        status=status,
        answer=dict(result.answer),
        events=tuple(TraceEvent.from_dict(step) for step in result.plan_steps),
        decisions=tuple(Decision.from_dict(d) for d in result.decisions),
        bound_exceeded=dict(result.bound_exceeded) if result.bound_exceeded else None,
        error={"code": "", "message": result.error} if result.error else None,
    )


def specialist_result_from_trace(trace: TraceResult, *, query: str) -> SpecialistResult:
    """Lower a public trace back to the supervisor-consumable result shape.

    The trace carries no query (the objective lives in the envelope), so the
    caller supplies it — the supervisor knows what it dispatched.
    """
    return SpecialistResult(
        domain=trace.agent.name,
        query=query,
        answer=dict(trace.answer),
        plan_steps=[event.to_dict() for event in trace.events],
        bound_exceeded=dict(trace.bound_exceeded) if trace.bound_exceeded else None,
        error=str(trace.error["message"]) if trace.error else None,
        decisions=[decision.to_dict() for decision in trace.decisions],
    )


__all__ = [
    "budget_consumed_from_reasoning",
    "budget_spec_from_reasoning",
    "envelope_for_dispatch",
    "reasoning_budget_from_spec",
    "specialist_result_from_trace",
    "trace_from_specialist_result",
]
