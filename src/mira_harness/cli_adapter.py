"""Generic subprocess foreign-agent adapter (ADR-051, optional).

The cross-process shape of the ADR-051 experiment: the child process gets the
envelope as JSON on stdin and must print exactly one TraceResult JSON document
to stdout. Any failure — non-zero exit, timeout, unparseable output, an
out-of-contract trace — returns ``TraceResult(status="error")``; this adapter
never raises.

The wall-clock timeout is the one budget the harness can *enforce* on a
foreign process (min of the injected ceiling and the envelope's
``max_seconds``); everything else in ``budget_consumed`` is self-reported.

Like every ``mira_harness`` module this imports ``mira_contracts`` + stdlib
only, so any host — not just the reference agent — can wrap a CLI agent.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

from mira_contracts.envelope import ContractViolation, ExecutionEnvelope
from mira_contracts.trace import AgentRef, TraceResult, validate_trace


class CliAgentAdapter:
    """An :class:`~mira_contracts.agent.EnvelopeRunner` over ``argv`` + timeout."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float = 60.0,
        name: str = "foreign-cli",
    ) -> None:
        if not argv:
            raise ValueError("argv must name the foreign agent command")
        self._argv = tuple(str(part) for part in argv)
        self._timeout_s = timeout_s
        self._name = name

    def card(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "description": (
                "Subprocess foreign agent: envelope JSON on stdin, one "
                "TraceResult JSON document on stdout (ADR-051)."
            ),
            "version": "1",
            "capabilities": {
                "tool_prefixes": [f"{self._name}."],
                "keywords": [],
            },
        }

    def _error(self, envelope: ExecutionEnvelope, code: str, message: str) -> TraceResult:
        return TraceResult(
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            agent=AgentRef(name=self._name, kind="foreign", version="1"),
            status="error",
            error={"code": code, "message": message},
        )

    def run(self, envelope: ExecutionEnvelope) -> TraceResult:
        timeout = min(self._timeout_s, envelope.budget.max_seconds)
        try:
            completed = subprocess.run(
                self._argv,
                input=json.dumps(envelope.to_dict()),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return self._error(
                envelope, "timeout", f"foreign agent exceeded {timeout}s wall clock"
            )
        except OSError as exc:
            return self._error(envelope, "spawn_failed", str(exc))

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            return self._error(
                envelope,
                "nonzero_exit",
                f"foreign agent exited {completed.returncode}: {detail}",
            )

        try:
            document = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return self._error(envelope, "bad_output", f"stdout is not JSON: {exc}")

        try:
            return validate_trace(document)
        except ContractViolation as exc:
            return self._error(envelope, "invalid_trace", exc.message)
        except Exception as exc:  # noqa: BLE001 — non-mapping output lands here
            return self._error(envelope, "invalid_trace", str(exc))


__all__ = ["CliAgentAdapter"]
