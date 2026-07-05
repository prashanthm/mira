"""Shared fixtures for the eval harness (ADR-045).

Evals run fully offline against the demo domains — same wiring the tests use,
via :mod:`mira.orchestration.specialists.demo`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.supervisor import Supervisor

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
HANDBOOK = str(FIXTURES / "handbook.md")
LEDGER = str(FIXTURES / "ledger.csv")


@pytest.fixture()
def supervisor() -> Supervisor:
    return Supervisor(build_demo_registry(HANDBOOK, LEDGER))
