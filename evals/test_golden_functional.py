"""Golden functional evals (ADR-045): demo-domain golden Q/A through the supervisor."""

from __future__ import annotations

import pytest

from evals.regression_gate import GOLDENS_DIR, load_golden_cases
from evals.trace_scoring import score_trace

CASES = load_golden_cases(GOLDENS_DIR)


def test_golden_set_is_nonempty():
    assert len(CASES) >= 6


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_case(supervisor, case):
    result = supervisor.invoke(case["query"], thread_id=f"golden:{case['id']}")

    assert result.routed_domain == case["domain"], (
        f"routed to {result.routed_domain!r}, expected {case['domain']!r}"
    )
    assert result.results, "no specialist result collected"

    answer = result.results[0].get("answer") or {}
    for key, expected in case["expect"].items():
        assert answer.get(key) == expected, (
            f"answer[{key!r}] = {answer.get(key)!r}, expected {expected!r}"
        )

    # Every golden answer must carry a structurally perfect trace: visible plan,
    # grounded claim→source attribution, within budget, error free.
    trace = score_trace(result.results[0])
    assert trace.score == 1.0, trace.to_dict()
