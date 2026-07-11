"""Tests for the subprocess CLI foreign-agent adapter (ADR-051).

Offline-only: every child process is this same Python interpreter running an
inline script (subprocess-of-self) — no network, no external binaries.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from mira_contracts.envelope import BudgetSpec, ExecutionEnvelope
from mira_harness.cli_adapter import CliAgentAdapter

CHILD_ECHO = textwrap.dedent(
    """
    import json, sys
    envelope = json.load(sys.stdin)
    token = envelope["objective"].rsplit(":", 1)[-1].strip().split()[-1].lower()
    trace = {
        "trace_version": "1",
        "task_id": envelope["task_id"],
        "correlation_id": envelope.get("correlation_id", ""),
        "agent": {"name": "cli-echo", "kind": "foreign", "version": "1"},
        "status": "ok",
        "answer": {
            "echo": token,
            "provenance": {
                "source_type": "foreign-cli.child",
                "source_id": envelope["task_id"],
            },
        },
        "events": [
            {"event": "plan_step", "phase": "plan", "detail": "plan", "index": 0},
            {"event": "plan_step", "phase": "act", "detail": "act", "index": 1},
            {"event": "plan_step", "phase": "observe", "detail": "obs", "index": 2},
        ],
        "decisions": [],
        "costs": [
            {
                "provider": "cli",
                "model": "child",
                "cost": 0.0,
                "latency_ms": 1.0,
                "self_reported": True,
                "tokens": 0,
                "tool": "",
            }
        ],
        "budget_consumed": {"steps": 1, "tokens": 1, "seconds": 0.0, "cost": 0.0},
        "bound_exceeded": None,
        "error": None,
    }
    print(json.dumps(trace))
    """
)


def _adapter(script: str, **kwargs) -> CliAgentAdapter:
    return CliAgentAdapter([sys.executable, "-c", script], **kwargs)


def _envelope(objective: str = "delegate: hello", **kwargs) -> ExecutionEnvelope:
    return ExecutionEnvelope(task_id="cli:t1", objective=objective, **kwargs)


def test_round_trip_through_a_child_process():
    trace = _adapter(CHILD_ECHO).run(_envelope("delegate: middleware"))
    assert trace.status == "ok"
    assert trace.answer["echo"] == "middleware"
    assert trace.task_id == "cli:t1"
    assert trace.agent.kind == "foreign"
    assert trace.costs[0].self_reported


def test_timeout_is_enforced_wall_clock():
    trace = _adapter("import time; time.sleep(5)", timeout_s=0.2).run(_envelope())
    assert trace.status == "error"
    assert trace.error["code"] == "timeout"


def test_envelope_max_seconds_caps_the_timeout():
    trace = _adapter("import time; time.sleep(5)", timeout_s=60.0).run(
        _envelope(budget=BudgetSpec(max_seconds=0.2))
    )
    assert trace.status == "error"
    assert trace.error["code"] == "timeout"


def test_nonzero_exit_degrades_to_error():
    trace = _adapter("import sys; sys.exit(3)").run(_envelope())
    assert trace.status == "error"
    assert trace.error["code"] == "nonzero_exit"


def test_non_json_output_degrades_to_error():
    trace = _adapter("print('nonsense')").run(_envelope())
    assert trace.status == "error"
    assert trace.error["code"] == "bad_output"


def test_out_of_contract_child_trace_degrades_to_error():
    trace = _adapter("print('{\"trace_version\": \"1\"}')").run(_envelope())
    assert trace.status == "error"
    assert trace.error["code"] == "invalid_trace"


def test_empty_argv_is_rejected():
    with pytest.raises(ValueError):
        CliAgentAdapter([])


def test_registry_with_foreign_is_a_no_op_without_the_env(monkeypatch):
    from mira.app import _registry_with_foreign

    monkeypatch.delenv("FOREIGN_AGENT_CMD", raising=False)
    assert _registry_with_foreign(None) is None
    monkeypatch.setenv("FOREIGN_AGENT_CMD", "   ")
    assert _registry_with_foreign(None) is None


def test_registry_with_foreign_routes_a_cli_agent(tmp_path, monkeypatch):
    from mira.app import _registry_with_foreign
    from mira.orchestration.supervisor import Supervisor

    script = tmp_path / "child.py"
    script.write_text(CHILD_ECHO)
    monkeypatch.setenv("FOREIGN_AGENT_CMD", f'"{sys.executable}" "{script}"')

    registry = _registry_with_foreign(None)
    assert registry is not None
    assert [card.name for card in registry.cards()] == ["foreign-cli"]

    result = Supervisor(registry).invoke(
        "delegate to the external foreign partner: hello", thread_id="t"
    )
    assert result.routed_domain == "foreign-cli"
    assert result.results[0]["answer"]["echo"] == "hello"
