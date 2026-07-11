"""Regression gate (ADR-045): run the golden set programmatically, return pass/fail.

This is the callable the versioning registry's eval-gated promotion consumes
(ADR-012 ``eval_gate``) and the release preflight runs before any tag. It uses
no pytest machinery so it can gate promotions in-process.

The agent-agnostic core (case loading, envelope lifting, criteria checking)
lives in :mod:`mira_harness.gate` (ADR-050); this module is the Mira wiring on
top: the default demo supervisor and the Mira-only routing assertion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mira_harness.gate import (
    MIN_TRACE_SCORE,
    GateReport,
    check_success_criteria,
    envelope_from_case,
    load_golden_cases as _load_golden_cases,
)

from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.contracts_bridge import trace_from_specialist_result
from mira.orchestration.foreign import register_foreign_stub
from mira.orchestration.specialist_scaffold import SpecialistResult
from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.supervisor import Supervisor

GOLDENS_DIR = Path(__file__).parent / "goldens"
_FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def build_eval_registry() -> AgentCardRegistry:
    """The registry every eval runs against: demo domains + the ADR-051 foreign stub.

    Shared by the pytest fixture (``evals/conftest.py``) and this gate's
    default supervisor so the golden set — foreign cases included — gates
    ADR-012 promotions.
    """
    registry = build_demo_registry(
        str(_FIXTURES / "handbook.md"), str(_FIXTURES / "ledger.csv")
    )
    register_foreign_stub(registry)
    return registry


def load_golden_cases(goldens_dir: Path | str = GOLDENS_DIR) -> list[dict[str, Any]]:
    """Load all golden cases from ``*.jsonl`` files under ``goldens_dir``."""
    return _load_golden_cases(goldens_dir)


def _check_case(supervisor: Supervisor, case: dict[str, Any]) -> dict[str, Any] | None:
    """Run one golden case; return a failure record or None on pass."""
    result = supervisor.invoke(case["query"], thread_id=f"gate:{case['id']}")
    if result.routed_domain != case["domain"]:
        return {
            "id": case["id"],
            "reason": f"routed to {result.routed_domain!r}, expected {case['domain']!r}",
        }
    if not result.results:
        return {"id": case["id"], "reason": "no specialist result collected"}

    envelope = envelope_from_case(case)
    trace = trace_from_specialist_result(
        SpecialistResult(**result.results[0]), task_id=envelope.task_id
    )
    reason = check_success_criteria(trace, envelope.success_criteria)
    if reason:
        return {"id": case["id"], "reason": reason}
    return None


def run_gate(
    goldens_dir: Path | str = GOLDENS_DIR,
    *,
    supervisor: Supervisor | None = None,
) -> GateReport:
    """Run every golden case through the supervisor; report failures.

    An empty golden set fails the gate — a gate that checks nothing must not
    green-light a promotion.
    """
    resolved = supervisor or Supervisor(build_eval_registry())
    report = GateReport()
    for case in load_golden_cases(goldens_dir):
        report.total += 1
        failure = _check_case(resolved, case)
        if failure:
            report.failures.append(failure)
    return report


def eval_gate() -> bool:
    """The ADR-012 promotion-gate callable: True only if the full golden set passes."""
    return run_gate().passed


__all__ = [
    "GateReport",
    "MIN_TRACE_SCORE",
    "build_eval_registry",
    "eval_gate",
    "load_golden_cases",
    "run_gate",
]
