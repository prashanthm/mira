"""Quality trigger for model-tier escalation (ADR-052).

Agent-agnostic: operates on the shared result mapping shape (a
``SpecialistResult.to_dict()`` — byte-compatible with the public
``TraceResult`` ``answer``/``plan_steps``/``bound_exceeded``/``error``
fields), reusing the structural checks the governance plane already ships.
Deterministic and offline like everything in this package.

Terminology fence: "escalation" unqualified means HITL (ADR-039, in the
reference agent's core); this module only ever decides whether a *model-tier*
escalation is warranted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mira_harness.policy import GroundednessChecker
from mira_harness.scoring import score_trace

UNGROUNDED_REASON = "ungrounded_answer"
BOUND_EXCEEDED_REASON = "bound_exceeded"
LOW_TRACE_SCORE_REASON = "low_trace_score"


@dataclass
class EscalationTrigger:
    """Decide whether a result is structurally poor enough to retry stronger.

    Reasons, in check order: ``ungrounded_answer`` (the ADR-038/045
    provenance rule via :class:`GroundednessChecker`), ``bound_exceeded``
    (the run hit a safety ceiling), ``low_trace_score`` (aggregate structural
    score below ``min_trace_score``). Returns ``None`` when the result needs
    no escalation.
    """

    groundedness: GroundednessChecker = field(default_factory=GroundednessChecker)
    min_trace_score: float = 0.75

    def check(self, result: Mapping[str, Any]) -> str | None:
        if self.groundedness.check(result) is not None:
            return UNGROUNDED_REASON
        if result.get("bound_exceeded"):
            return BOUND_EXCEEDED_REASON
        if score_trace(result).score < self.min_trace_score:
            return LOW_TRACE_SCORE_REASON
        return None


__all__ = [
    "BOUND_EXCEEDED_REASON",
    "LOW_TRACE_SCORE_REASON",
    "UNGROUNDED_REASON",
    "EscalationTrigger",
]
