"""Public, agent-agnostic execution contracts (ADR-049).

Two versioned document contracts — :class:`ExecutionEnvelope` (task input) and
:class:`TraceResult` (task output) — plus the :class:`EnvelopeRunner` Protocol
any agent implements to be governable by the ``mira_harness`` planes.

This package must stay importable with zero ``mira``/``mira_harness`` imports
(ADR-050 direction rule, lint-enforced): stdlib + ``jsonschema`` only.
"""

from __future__ import annotations

from mira_contracts.agent import EnvelopeRunner
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
from mira_contracts.trace import (
    TRACE_VERSION,
    AgentRef,
    BudgetConsumed,
    CostRecord,
    Decision,
    TraceEvent,
    TraceResult,
    validate_trace,
)

CONTRACTS_VERSION = "1"

__all__ = [
    "CONTRACTS_VERSION",
    "ENVELOPE_VERSION",
    "TRACE_VERSION",
    "AgentRef",
    "BudgetConsumed",
    "BudgetSpec",
    "Constraints",
    "ContextRef",
    "ContractViolation",
    "CostRecord",
    "Decision",
    "EnvelopeRunner",
    "ExecutionEnvelope",
    "SuccessCriterion",
    "ToolGrant",
    "TraceEvent",
    "TraceResult",
    "validate_envelope",
    "validate_trace",
]
