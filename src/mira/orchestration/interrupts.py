"""LangGraph HITL interrupt surfacing shared by runtime and reasoning loops."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class CompiledGraph(Protocol):
    """Minimal compiled LangGraph app surface needed for interrupt annotation."""

    def get_state(self, config: dict[str, Any]) -> Any: ...


def annotate_graph_interrupt(
    app: CompiledGraph,
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Surface a pause as ``__interrupt__`` on the result dict.

    LangGraph's ``invoke`` return value does not carry the interrupt; the pause is
    observable via ``get_state(config).next`` (the node(s) still to run). Re-expose
    it as ``__interrupt__`` so ``is_graph_paused`` stays a simple result check.
    """
    snapshot = app.get_state(config)
    if snapshot.next:
        pending = [
            intr for task in snapshot.tasks for intr in (task.interrupts or ())
        ]
        result = dict(result)
        result["__interrupt__"] = pending or list(snapshot.next)
    return result


def is_graph_paused(result: Mapping[str, Any]) -> bool:
    return bool(result.get("__interrupt__"))
