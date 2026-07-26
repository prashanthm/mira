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
import logging
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


#: The system prompt for a ROUTED-turn synthesis (one specialist, not the
#: analyze fan-out). Grounded, no fabrication; the per-card synthesis_hint
#: carries any domain-specific shape (e.g. the trade-analyst's review
#: structure). Domain-generic on purpose — a new card never edits this.
_TURN_SYSTEM_PROMPT = (
    "You are the answer synthesizer. A specialist gathered structured DATA for "
    "the user's request; write the decision-useful answer from it.\n"
    "HARD RULES:\n"
    "1. Use ONLY facts in the specialist data — never invent numbers, dates, "
    "levels, or recommendations.\n"
    "2. Be specific: cite the actual figures from the data.\n"
    "3. If the specialist returned an error or no data, say so plainly.\n"
    "4. No preamble, no disclaimers. Answer directly."
)
# Every model-synthesized turn (advisor, a single facet, the general chat
# fallback) emits the A2UI contract too — so the Vantage renderer gets
# structured sections uniformly, not just the specialists that opted in
# per-card. Prose stays the graceful fallback (parseMira → clean text).
from mira.orchestration.ui_contract import with_contract as _with_contract  # noqa: E402

_TURN_SYSTEM_PROMPT = _with_contract(_TURN_SYSTEM_PROMPT)


_CLASSIFY_SYSTEM = (
    "You are a router. Given a user request and a list of specialist DOMAINS "
    "(name: what it handles), reply with the single best domain NAME to handle "
    "it, or the exact word NONE if none fits. Output ONLY the name — no prose, "
    "no punctuation, no explanation."
)


def classify_with_model(llm: Any, query: str, cards) -> str | None:
    """LLM intent-routing FALLBACK — used only when the deterministic keyword
    matcher scores zero. Returns a valid card name from ``cards`` or None
    (never a guess: a reply that isn't an exact card name → None → general
    path). Pure + defensive: any model failure degrades to None, never raises,
    so a flaky gateway can only fall back to today's behavior, never break the
    route."""
    cards = list(cards)
    names = {c.name for c in cards}
    catalog = "\n".join(f"- {c.name}: {c.description}" for c in cards)
    user = f"REQUEST:\n{query}\n\nDOMAINS:\n{catalog}\n\nBest domain name (or NONE):"
    try:
        from mira.model.gateway import call_context
        from mira.orchestration.synthesis import SYNTHESIS_TIER, _invoke
        with call_context("classify"):
            reply = (_invoke(llm, _CLASSIFY_SYSTEM, user, tier=SYNTHESIS_TIER) or "").strip()
    except Exception:  # noqa: BLE001 — routing must never crash on a model failure
        logging.getLogger(__name__).exception("llm route classify failed")
        return None
    token = reply.split()[0].strip().strip(".:,").lower() if reply else ""
    for n in names:                       # exact (case-insensitive) card name only
        if token == n.lower():
            return n
    return None


def _synthesis_hint(registry: AgentCardRegistry, domain: str | None) -> str:
    """The routed card's own synthesis instruction (its review structure /
    caveats), or empty when unavailable."""
    if not domain:
        return ""
    try:
        for card in registry.cards():
            if card.name == domain:
                return card.synthesis_hint or ""
    except Exception:  # noqa: BLE001 — a registry probe must never break synthesis
        pass
    return ""


def _synthesize_with_model(llm: Any, query: str, results: list[dict[str, Any]],
                           hint: str) -> str:
    """Weave the routed specialist's answer into prose via the model. Returns
    "" on any failure so the caller falls back to the deterministic digest —
    synthesis must never blank the answer."""
    from mira.orchestration.synthesis import SYNTHESIS_TIER, _invoke

    payload = _synthesize(results)          # the [domain]{json} the model reads
    user = f"USER REQUEST:\n{query}\n\nSPECIALIST DATA:\n{payload}"
    if hint:
        user += f"\n\nDOMAIN GUIDANCE (how to shape this answer):\n{hint}"
    try:
        from mira.model.gateway import call_context
        with call_context("turn_synthesis"):
            return _invoke(llm, _TURN_SYSTEM_PROMPT, user, tier=SYNTHESIS_TIER).strip()
    except Exception:  # noqa: BLE001 — degrade to deterministic, never crash
        # loud on the way down: a provider break (e.g. a retired model name)
        # otherwise degrades EVERY routed turn to the raw digest, silently
        logging.getLogger(__name__).exception("turn synthesis model call failed")
        return ""


class Supervisor:
    """Routing graph over an :class:`AgentCardRegistry` (ADR-014)."""

    def __init__(self, registry: AgentCardRegistry, *, llm: Any | None = None) -> None:
        self._registry = registry
        # Optional model gateway view. When present, the synthesize node weaves
        # the routed specialist's answer into decision-useful PROSE (ADR-014
        # left synthesis deterministic — "[domain] {json}" — as a Phase-1
        # placeholder; a live model turns it into a real answer). Absent (tests,
        # offline, eval registry) → the deterministic digest, unchanged.
        self._llm = llm
        self._app = self._build_graph().compile()

    def _build_graph(self) -> StateGraph:
        registry = self._registry

        def classify(state: SupervisorState) -> dict[str, Any]:
            query = state.get("query", "")
            card = registry.match(query)          # deterministic fast path
            if card is not None:
                return {"routed_domain": card.name}
            # keyword miss → LLM intent fallback (only when a model is wired).
            # Keeps the fast path pure/deterministic; the model call lands ONLY
            # on the ambiguous tail keywords can't cover ("how well did I time
            # that buy?"). A None result keeps today's general-path behavior.
            if self._llm is not None:
                name = classify_with_model(self._llm, query, registry.cards())
                if name:
                    return {"routed_domain": name}
            return {"routed_domain": FALLBACK_DOMAIN}

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
            results = state.get("results") or []
            if self._llm is not None:
                hint = _synthesis_hint(registry, state.get("routed_domain"))
                prose = _synthesize_with_model(self._llm, state.get("query", ""),
                                               results, hint)
                if prose:
                    return {"synthesis": prose}
            # no model, or a model failure — the deterministic digest (never
            # blanks the answer; the ADR-014 Phase-1 contract)
            return {"synthesis": _synthesize(results)}

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
