"""TraceResult v1 — the agent-agnostic task output contract (ADR-049).

The ``answer``/``events``/``bound_exceeded`` shapes are deliberately
byte-compatible with Mira's internal ``SpecialistResult.to_dict()`` fields:
that compatibility is what lets the governance plane (groundedness, drift,
scoring, gate, decision traces) apply to foreign traces with zero changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mira_contracts.envelope import ContractViolation, _validate_document

TRACE_VERSION = "1"

STATUSES = ("ok", "error", "bound_exceeded", "paused")
AGENT_KINDS = ("specialist", "foreign")
DECISION_KINDS = ("routing", "tool_call", "guardrail", "escalation")


@dataclass(frozen=True, slots=True)
class AgentRef:
    """Which agent produced the trace."""

    name: str
    kind: str
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "version": self.version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentRef:
        return cls(
            name=str(data["name"]),
            kind=str(data["kind"]),
            version=str(data.get("version", "")),
        )


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One reasoning event — byte-compatible with a ``plan_steps`` entry."""

    phase: str
    detail: str
    index: int
    event: str = "plan_step"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "phase": self.phase,
            "detail": self.detail,
            "index": self.index,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceEvent:
        return cls(
            event=str(data.get("event", "plan_step")),
            phase=str(data["phase"]),
            detail=str(data["detail"]),
            index=int(data["index"]),
        )


@dataclass(frozen=True, slots=True)
class Decision:
    """One recorded decision (routing choice, tool call, guardrail finding…)."""

    kind: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": dict(self.detail)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Decision:
        return cls(kind=str(data["kind"]), detail=dict(data.get("detail", {})))


@dataclass(frozen=True, slots=True)
class CostRecord:
    """One model/tool call's cost. ``self_reported`` marks unverified numbers.

    Native runs record gateway-measured costs (``self_reported=False``);
    foreign agents report their own (``self_reported=True``) so downstream
    consumers — the ledger, anomaly detection — can weigh trust accordingly.
    """

    provider: str
    model: str
    cost: float
    latency_ms: float
    self_reported: bool
    tokens: int = 0
    tool: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "self_reported": self.self_reported,
            "tokens": self.tokens,
            "tool": self.tool,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CostRecord:
        return cls(
            provider=str(data["provider"]),
            model=str(data["model"]),
            cost=float(data["cost"]),
            latency_ms=float(data["latency_ms"]),
            self_reported=bool(data["self_reported"]),
            tokens=int(data.get("tokens", 0)),
            tool=str(data.get("tool", "")),
        )


@dataclass(frozen=True, slots=True)
class BudgetConsumed:
    """What the run actually consumed against its ``BudgetSpec`` ceilings."""

    steps: int = 0
    tokens: int = 0
    seconds: float = 0.0
    cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "tokens": self.tokens,
            "seconds": self.seconds,
            "cost": self.cost,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BudgetConsumed:
        return cls(
            steps=int(data.get("steps", 0)),
            tokens=int(data.get("tokens", 0)),
            seconds=float(data.get("seconds", 0.0)),
            cost=float(data.get("cost", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class TraceResult:
    """Versioned, serializable task output any governable agent emits.

    ``answer`` preserves the recursive ADR-045 grounding rule: claims carry a
    nested ``provenance{source_type, source_id}`` mapping. ``error`` is a
    structured ``{code, message}`` mapping or None. ``bound_exceeded`` is the
    verbatim ``asdict(BoundExceeded)`` shape or None.
    """

    task_id: str
    agent: AgentRef
    trace_version: str = TRACE_VERSION
    correlation_id: str = ""
    status: str = "ok"
    answer: dict[str, Any] = field(default_factory=dict)
    events: tuple[TraceEvent, ...] = ()
    decisions: tuple[Decision, ...] = ()
    costs: tuple[CostRecord, ...] = ()
    budget_consumed: BudgetConsumed = field(default_factory=BudgetConsumed)
    bound_exceeded: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_version": self.trace_version,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "agent": self.agent.to_dict(),
            "status": self.status,
            "answer": dict(self.answer),
            "events": [event.to_dict() for event in self.events],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "costs": [cost.to_dict() for cost in self.costs],
            "budget_consumed": self.budget_consumed.to_dict(),
            "bound_exceeded": dict(self.bound_exceeded) if self.bound_exceeded else None,
            "error": dict(self.error) if self.error else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceResult:
        bound = data.get("bound_exceeded")
        error = data.get("error")
        return cls(
            trace_version=str(data.get("trace_version", TRACE_VERSION)),
            task_id=str(data["task_id"]),
            correlation_id=str(data.get("correlation_id", "")),
            agent=AgentRef.from_dict(data["agent"]),
            status=str(data.get("status", "ok")),
            answer=dict(data.get("answer", {})),
            events=tuple(TraceEvent.from_dict(e) for e in data.get("events", ())),
            decisions=tuple(Decision.from_dict(d) for d in data.get("decisions", ())),
            costs=tuple(CostRecord.from_dict(c) for c in data.get("costs", ())),
            budget_consumed=BudgetConsumed.from_dict(data.get("budget_consumed", {})),
            bound_exceeded=dict(bound) if isinstance(bound, Mapping) else None,
            error=dict(error) if isinstance(error, Mapping) else None,
        )


def validate_trace(doc: Mapping[str, Any] | TraceResult) -> TraceResult:
    """Fail-closed validation; returns the parsed trace on success."""
    data = doc.to_dict() if isinstance(doc, TraceResult) else dict(doc)
    _validate_document(
        data,
        schema_file="trace_result.v1.json",
        version_key="trace_version",
        expected_version=TRACE_VERSION,
        label="TraceResult",
    )
    return TraceResult.from_dict(data)


__all__ = [
    "AGENT_KINDS",
    "DECISION_KINDS",
    "STATUSES",
    "TRACE_VERSION",
    "AgentRef",
    "BudgetConsumed",
    "ContractViolation",
    "CostRecord",
    "Decision",
    "TraceEvent",
    "TraceResult",
    "validate_trace",
]
