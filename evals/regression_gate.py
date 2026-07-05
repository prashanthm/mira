"""Regression gate (ADR-045): run the golden set programmatically, return pass/fail.

This is the callable the versioning registry's eval-gated promotion consumes
(ADR-012 ``eval_gate``) and the release preflight runs before any tag. It uses
no pytest machinery so it can gate promotions in-process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.supervisor import Supervisor

from evals.trace_scoring import score_trace

GOLDENS_DIR = Path(__file__).parent / "goldens"
_FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
MIN_TRACE_SCORE = 1.0  # goldens must produce structurally perfect traces


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


def load_golden_cases(goldens_dir: Path | str = GOLDENS_DIR) -> list[dict[str, Any]]:
    """Load all golden cases from ``*.jsonl`` files under ``goldens_dir``."""
    cases: list[dict[str, Any]] = []
    for path in sorted(Path(goldens_dir).glob("*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


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

    answer = result.results[0].get("answer") or {}
    for key, expected in case["expect"].items():
        if answer.get(key) != expected:
            return {
                "id": case["id"],
                "reason": f"answer[{key!r}] = {answer.get(key)!r}, expected {expected!r}",
            }

    trace = score_trace(result.results[0])
    if trace.score < MIN_TRACE_SCORE:
        return {"id": case["id"], "reason": f"trace score {trace.score} < {MIN_TRACE_SCORE}"}
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
    resolved = supervisor or Supervisor(
        build_demo_registry(str(_FIXTURES / "handbook.md"), str(_FIXTURES / "ledger.csv"))
    )
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


__all__ = ["GateReport", "eval_gate", "load_golden_cases", "run_gate"]
