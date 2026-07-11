"""Generic regression gate over the public contracts (ADR-045/049/050).

The agent-agnostic core of the eval gate: load golden cases, lift each into
an :class:`ExecutionEnvelope`, run them through any envelope runner, and
check the envelope's success criteria against the returned trace. The
reference agent's Mira-specific wiring (supervisor construction, routing
assertions) lives in ``evals/regression_gate.py`` on top of this module.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mira_contracts.envelope import (
    ContractViolation,
    ExecutionEnvelope,
    SuccessCriterion,
)
from mira_contracts.trace import TraceResult, validate_trace

from mira_harness.scoring import score_trace

MIN_TRACE_SCORE = 1.0  # goldens must produce structurally perfect traces

EnvelopeRunnerFn = Callable[[ExecutionEnvelope], TraceResult]


@dataclass
class GateReport:
    """Outcome of one regression-gate run."""

    total: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.total > 0 and not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "passed": self.passed, "failures": self.failures}


def load_golden_cases(goldens_dir: Path | str) -> list[dict[str, Any]]:
    """Load all golden cases from ``*.jsonl`` files under ``goldens_dir``."""
    cases: list[dict[str, Any]] = []
    for path in sorted(Path(goldens_dir).glob("*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def envelope_from_case(
    case: Mapping[str, Any],
    *,
    min_trace_score: float = MIN_TRACE_SCORE,
) -> ExecutionEnvelope:
    """Lift one golden case into the public envelope contract.

    ``expect`` entries become ``answer_field`` criteria; every golden also
    demands a grounded, structurally perfect trace. The case's ``domain`` is
    routing metadata for the dispatching harness, not part of the envelope.
    """
    criteria: list[SuccessCriterion] = [
        SuccessCriterion(kind="answer_field", key=key, expected=expected)
        for key, expected in dict(case.get("expect") or {}).items()
    ]
    criteria.append(SuccessCriterion(kind="min_trace_score", threshold=min_trace_score))
    return ExecutionEnvelope(
        task_id=f"gate:{case['id']}",
        objective=str(case["query"]),
        success_criteria=tuple(criteria),
    )


def _scoring_shape(trace: TraceResult) -> dict[str, Any]:
    """The SpecialistResult-shaped mapping the scoring dimensions read
    (byte-compatible with the trace's answer/events/bound_exceeded — ADR-049)."""
    return {
        "answer": trace.answer,
        "plan_steps": [event.to_dict() for event in trace.events],
        "bound_exceeded": trace.bound_exceeded,
        "error": trace.error["message"] if trace.error else None,
    }


def check_success_criteria(
    trace: TraceResult,
    criteria: Sequence[SuccessCriterion],
) -> str | None:
    """Check a trace against envelope criteria; return a failure reason or None."""
    shaped = _scoring_shape(trace)
    for criterion in criteria:
        if criterion.kind == "answer_field":
            actual = trace.answer.get(criterion.key)
            if actual != criterion.expected:
                return (
                    f"answer[{criterion.key!r}] = {actual!r}, "
                    f"expected {criterion.expected!r}"
                )
        elif criterion.kind == "grounded":
            if not score_trace(shaped).grounded:
                return "answer is not grounded (no provenance attribution)"
        elif criterion.kind == "min_trace_score":
            score = score_trace(shaped).score
            if score < criterion.threshold:
                return f"trace score {score} < {criterion.threshold}"
    return None


def run_gate(
    cases: Sequence[Mapping[str, Any]],
    runner: EnvelopeRunnerFn,
    *,
    min_trace_score: float = MIN_TRACE_SCORE,
) -> GateReport:
    """Run golden cases through any envelope runner; report failures.

    Fail-closed twice over: an empty case list fails the gate (a gate that
    checks nothing must not green-light a promotion), and a runner exception
    or out-of-contract trace is a failure record, never an escaping crash.
    """
    report = GateReport()
    for case in cases:
        report.total += 1
        envelope = envelope_from_case(case, min_trace_score=min_trace_score)
        try:
            trace = validate_trace(runner(envelope))
        except ContractViolation as exc:
            report.failures.append({"id": case["id"], "reason": f"invalid trace: {exc}"})
            continue
        except Exception as exc:  # noqa: BLE001 — gate reports, never crashes
            report.failures.append({"id": case["id"], "reason": f"runner error: {exc}"})
            continue
        reason = check_success_criteria(trace, envelope.success_criteria)
        if reason:
            report.failures.append({"id": case["id"], "reason": reason})
    return report


__all__ = [
    "MIN_TRACE_SCORE",
    "EnvelopeRunnerFn",
    "GateReport",
    "check_success_criteria",
    "envelope_from_case",
    "load_golden_cases",
    "run_gate",
]
