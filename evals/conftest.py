"""Shared fixtures for the eval harness (ADR-045).

Evals run fully offline against the demo domains — same wiring the tests use,
via :mod:`mira.orchestration.specialists.demo`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.orchestration.supervisor import Supervisor

from evals.regression_gate import build_eval_registry

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
HANDBOOK = str(FIXTURES / "handbook.md")
LEDGER = str(FIXTURES / "ledger.csv")


@pytest.fixture()
def supervisor() -> Supervisor:
    # Demo domains + the ADR-051 foreign stub — the same registry the
    # regression gate's default supervisor uses.
    return Supervisor(build_eval_registry())
