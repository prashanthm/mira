"""The runner Protocol connecting the two contracts (ADR-049/051).

Synchronous by design, matching every existing seam in the reference agent
(``ILLMProvider``, ``SpanObserver``, ``TextDetector``). An agent implements
this Protocol — against ``mira_contracts`` only — to become governable by the
``mira_harness`` planes and routable behind a foreign-specialist wrapper.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from mira_contracts.envelope import ExecutionEnvelope
from mira_contracts.trace import TraceResult


@runtime_checkable
class EnvelopeRunner(Protocol):
    """Any agent that accepts an envelope and returns a trace."""

    def card(self) -> dict[str, Any]:
        """A2A-shaped discovery card (the ``AgentCard.to_dict()`` shape)."""
        ...

    def run(self, envelope: ExecutionEnvelope) -> TraceResult:
        """Execute the enveloped task and return the trace."""
        ...


__all__ = ["EnvelopeRunner"]
