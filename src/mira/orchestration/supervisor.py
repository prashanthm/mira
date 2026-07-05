"""Supervisor routing graph (ADR-014): classify → dispatch → synthesize.

The orchestrator-worker topology ADR-014 decided: a small LangGraph routing
graph classifies an incoming query against the agent-card registry (ADR-035),
dispatches to the matched specialist's state-isolated subgraph, and collects
the :class:`~mira.orchestration.specialist_scaffold.SpecialistResult` contract
into a :class:`SupervisorResult`. No card match falls back to a structured
general answer rather than an error — the supervisor never guesses a domain.

Routing is discovery-driven: adding a specialist is one ``registry.register``
call; the graph never changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from mira.orchestration.agent_cards import AgentCardRegistry

FALLBACK_DOMAIN = ""


class SupervisorState(TypedDict, total=False):
    query: str
    thread_id: str
    routed_domain: str
    results: list[dict[str, Any]]
    synthesis: str
    error: str


@dataclass
class SupervisorResult:
    """Structured supervisor outcome: routing decision + collected specialist results."""

    query: str
    routed_domain: str | None
    results: list[dict[str, Any]] = field(default_factory=list)
    synthesis: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "routed_domain": self.routed_domain,
            "results": self.results,
            "synthesis": self.synthesis,
            "error": self.error,
        }


def _synthesize(results: list[dict[str, Any]]) -> str:
    """Deterministic synthesis: one attributed line per specialist answer.

    A real model-written synthesis slots in behind the same node once live
    providers are in play; the structure (per-domain attribution, errors kept
    visible) is the contract.
    """
    lines: list[str] = []
    for result in results:
        domain = result.get("domain", "?")
        if result.get("error"):
            lines.append(f"[{domain}] error: {result['error']}")
        else:
            lines.append(f"[{domain}] {json.dumps(result.get('answer', {}), sort_keys=True)}")
    return "\n".join(lines)


class Supervisor:
    """Routing graph over an :class:`AgentCardRegistry` (ADR-014)."""

    def __init__(self, registry: AgentCardRegistry) -> None:
        self._registry = registry
        self._app = self._build_graph().compile()

    def _build_graph(self) -> StateGraph:
        registry = self._registry

        def classify(state: SupervisorState) -> dict[str, Any]:
            card = registry.match(state.get("query", ""))
            return {"routed_domain": card.name if card else FALLBACK_DOMAIN}

        def dispatch(state: SupervisorState) -> dict[str, Any]:
            domain = state.get("routed_domain") or FALLBACK_DOMAIN
            query = state.get("query", "")
            thread_id = state.get("thread_id") or "supervisor"
            specialist = registry.resolve(domain)
            result = specialist.invoke(query, thread_id=thread_id)
            return {"results": [result.to_dict()]}

        def general(state: SupervisorState) -> dict[str, Any]:
            # No specialist matched: answer structurally, never guess a domain.
            query = state.get("query", "")
            return {
                "results": [],
                "synthesis": f"[general] no specialist matched: {query}",
            }

        def synthesize(state: SupervisorState) -> dict[str, Any]:
            return {"synthesis": _synthesize(state.get("results") or [])}

        def route_after_classify(state: SupervisorState) -> str:
            return "dispatch" if state.get("routed_domain") else "general"

        graph = StateGraph(SupervisorState)
        graph.add_node("classify", classify)
        graph.add_node("dispatch", dispatch)
        graph.add_node("general", general)
        graph.add_node("synthesize", synthesize)
        graph.add_edge(START, "classify")
        graph.add_conditional_edges("classify", route_after_classify, ["dispatch", "general"])
        graph.add_edge("dispatch", "synthesize")
        graph.add_edge("general", END)
        graph.add_edge("synthesize", END)
        return graph

    def invoke(self, query: str, *, thread_id: str) -> SupervisorResult:
        """Route ``query`` to the best specialist and collect its result."""
        state = self._app.invoke({"query": query, "thread_id": thread_id})
        routed = state.get("routed_domain") or None
        return SupervisorResult(
            query=query,
            routed_domain=routed,
            results=list(state.get("results") or []),
            synthesis=state.get("synthesis", ""),
            error=state.get("error"),
        )

    def fan_out(
        self,
        query: str,
        domains: list[str],
        *,
        thread_id: str,
    ) -> SupervisorResult:
        """Multi-specialist fan-out: dispatch ``query`` to each named domain.

        Phase-B slice: sequential dispatch + shared synthesis. Parallel dispatch
        and cross-specialist workflow composition land with ADR-015 (Phase F);
        the result contract is already the one that work consumes.
        """
        results: list[dict[str, Any]] = []
        for domain in domains:
            specialist = self._registry.resolve(domain)
            results.append(specialist.invoke(query, thread_id=thread_id).to_dict())
        return SupervisorResult(
            query=query,
            routed_domain=None,
            results=results,
            synthesis=_synthesize(results),
        )


__all__ = ["FALLBACK_DOMAIN", "Supervisor", "SupervisorResult", "SupervisorState"]
