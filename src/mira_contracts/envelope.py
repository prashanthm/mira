"""ExecutionEnvelope v1 — the agent-agnostic task input contract (ADR-049).

Dual representation: frozen dataclasses with ``to_dict``/``from_dict`` are the
code contract; ``schemas/execution_envelope.v1.json`` is the wire contract.
:func:`validate_envelope` is fail-closed — an unknown version or any schema
violation raises :class:`ContractViolation`, never a silent coercion.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

ENVELOPE_VERSION = "1"

SUCCESS_CRITERION_KINDS = ("answer_field", "grounded", "min_trace_score")


class ContractViolation(Exception):
    """A document failed fail-closed contract validation (ADR-049)."""

    def __init__(self, message: str, *, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


@lru_cache(maxsize=None)
def _schema(name: str) -> dict[str, Any]:
    text = resources.files("mira_contracts").joinpath(f"schemas/{name}").read_text("utf-8")
    return json.loads(text)


def _validate_document(
    doc: Mapping[str, Any],
    *,
    schema_file: str,
    version_key: str,
    expected_version: str,
    label: str,
) -> None:
    """Shared fail-closed validation core for both contracts."""
    version = doc.get(version_key)
    if version != expected_version:
        raise ContractViolation(
            f"{label} {version_key} must be {expected_version!r}, got {version!r}",
            details=["fail_closed=true"],
        )
    validator = Draft202012Validator(_schema(schema_file))
    errors = sorted(validator.iter_errors(dict(doc)), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ContractViolation(
            f"{label} schema violation at {path}: {first.message}",
            details=[f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
                     for e in errors],
        )


@dataclass(frozen=True, slots=True)
class ContextRef:
    """A reference to context an agent may fetch — never an inline payload."""

    kind: str
    id: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "description": self.description}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ContextRef:
        return cls(
            kind=str(data["kind"]),
            id=str(data["id"]),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class Constraints:
    """Behavioral constraints on a run (generalizes the specialist invoke kwargs)."""

    require_hitl: bool = False
    allow_destructive: bool = False
    max_iterations: int = 1
    disallowed: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_hitl": self.require_hitl,
            "allow_destructive": self.allow_destructive,
            "max_iterations": self.max_iterations,
            "disallowed": list(self.disallowed),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Constraints:
        return cls(
            require_hitl=bool(data.get("require_hitl", False)),
            allow_destructive=bool(data.get("allow_destructive", False)),
            max_iterations=int(data.get("max_iterations", 1)),
            disallowed=tuple(str(item) for item in data.get("disallowed", ())),
        )


@dataclass(frozen=True, slots=True)
class ToolGrant:
    """One tool grant: a name prefix plus the entitlement it requires.

    An envelope with **no grants allows no tools** — fail-closed, mirroring
    the specialist scaffold's no-tools branch and ADR-034/041 token narrowing.
    """

    name_prefix: str
    entitlement: str

    def to_dict(self) -> dict[str, Any]:
        return {"name_prefix": self.name_prefix, "entitlement": self.entitlement}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ToolGrant:
        return cls(name_prefix=str(data["name_prefix"]), entitlement=str(data["entitlement"]))


@dataclass(frozen=True, slots=True)
class BudgetSpec:
    """Declarative budget ceilings — the ADR-013 ``ReasoningBudget`` ceilings.

    Defaults intentionally match ``ReasoningBudget`` so a bridge round-trip is
    lossless. Enforcement strength varies by adapter (ADR-051): measured for
    native runs, self-reported or wall-clock-bounded for foreign runs.
    """

    max_steps: int = 10
    max_tokens: int = 8000
    max_seconds: float = 300.0
    max_cost: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
            "max_cost": self.max_cost,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BudgetSpec:
        return cls(
            max_steps=int(data.get("max_steps", 10)),
            max_tokens=int(data.get("max_tokens", 8000)),
            max_seconds=float(data.get("max_seconds", 300.0)),
            max_cost=float(data.get("max_cost", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class SuccessCriterion:
    """One machine-checkable success criterion (generalizes golden ``expect``).

    ``kind`` is one of :data:`SUCCESS_CRITERION_KINDS`: ``answer_field``
    (``answer[key] == expected``), ``grounded`` (the ADR-045 provenance rule),
    or ``min_trace_score`` (aggregate trace score ≥ ``threshold``).
    """

    kind: str
    key: str = ""
    expected: Any = None
    threshold: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "expected": self.expected,
            "threshold": self.threshold,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SuccessCriterion:
        return cls(
            kind=str(data["kind"]),
            key=str(data.get("key", "")),
            expected=data.get("expected"),
            threshold=float(data.get("threshold", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class ExecutionEnvelope:
    """Versioned, serializable task input any governable agent accepts."""

    task_id: str
    objective: str
    envelope_version: str = ENVELOPE_VERSION
    correlation_id: str = ""
    tenant: str = ""
    context_refs: tuple[ContextRef, ...] = ()
    constraints: Constraints = field(default_factory=Constraints)
    tool_grants: tuple[ToolGrant, ...] = ()
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    success_criteria: tuple[SuccessCriterion, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "tenant": self.tenant,
            "objective": self.objective,
            "context_refs": [ref.to_dict() for ref in self.context_refs],
            "constraints": self.constraints.to_dict(),
            "tool_grants": [grant.to_dict() for grant in self.tool_grants],
            "budget": self.budget.to_dict(),
            "success_criteria": [c.to_dict() for c in self.success_criteria],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExecutionEnvelope:
        return cls(
            envelope_version=str(data.get("envelope_version", ENVELOPE_VERSION)),
            task_id=str(data["task_id"]),
            correlation_id=str(data.get("correlation_id", "")),
            tenant=str(data.get("tenant", "")),
            objective=str(data["objective"]),
            context_refs=tuple(
                ContextRef.from_dict(ref) for ref in data.get("context_refs", ())
            ),
            constraints=Constraints.from_dict(data.get("constraints", {})),
            tool_grants=tuple(
                ToolGrant.from_dict(grant) for grant in data.get("tool_grants", ())
            ),
            budget=BudgetSpec.from_dict(data.get("budget", {})),
            success_criteria=tuple(
                SuccessCriterion.from_dict(c) for c in data.get("success_criteria", ())
            ),
        )


def validate_envelope(
    doc: Mapping[str, Any] | ExecutionEnvelope,
) -> ExecutionEnvelope:
    """Fail-closed validation; returns the parsed envelope on success."""
    data = doc.to_dict() if isinstance(doc, ExecutionEnvelope) else dict(doc)
    _validate_document(
        data,
        schema_file="execution_envelope.v1.json",
        version_key="envelope_version",
        expected_version=ENVELOPE_VERSION,
        label="ExecutionEnvelope",
    )
    return ExecutionEnvelope.from_dict(data)


__all__ = [
    "ENVELOPE_VERSION",
    "SUCCESS_CRITERION_KINDS",
    "BudgetSpec",
    "Constraints",
    "ContextRef",
    "ContractViolation",
    "ExecutionEnvelope",
    "SuccessCriterion",
    "ToolGrant",
    "validate_envelope",
]
