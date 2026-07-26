"""Agent cards and discovery registry (ADR-035 slice, ADR-014).

A specialist publishes an :class:`AgentCard` — discovery metadata in an
A2A-compatible shape — and registers it with an :class:`AgentCardRegistry`
alongside the invocable subgraph. The supervisor routes against the registry
(cards drive classification), so adding a domain never edits supervisor code.

This is the Phase-B slice of ADR-035: in-process cards + registry with a
deterministic keyword matcher. The full A2A surface (well-known URI serving,
remote discovery, signed cards) layers on later without changing this contract.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from mira.orchestration.specialist_scaffold import DomainSpec, SpecialistResult

_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]*")

CARD_SCHEMA_VERSION = "1"


def _singularize(w: str) -> str:
    """Conservative plural→singular fold so query tokens hit singular keywords
    (accounts→account, catalysts→catalyst, harvesting→harvest). Only the safe,
    high-frequency English endings — never touches short words or -ss."""
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"        # opportunities→opportunity
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]              # harvesting→harvest
    if w.endswith("es") and len(w) > 4 and not w.endswith(("sses", "ses")):
        return w[:-2]              # losses→loss? no: -ss guarded; catalysts handled below
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]              # accounts→account, catalysts→catalyst
    return w


def _query_tokens(query: str) -> set[str]:
    """The query's matchable token set. Each raw token also contributes its
    hyphen/period SUB-tokens (so 'over-allocated' → over, allocated, allocation
    via the fold) and a singular fold — matching stays whole-token equality
    against card keywords, just over a richer, normalized query set. Card
    keywords are untouched.
    """
    out: set[str] = set()
    for raw in _WORD.findall(query.lower()):
        parts = [raw, *re.split(r"[-.]", raw)]
        for p in parts:
            if not p:
                continue
            out.add(p)
            out.add(_singularize(p))
    return out


class UnknownAgentError(KeyError):
    """Raised when the registry cannot resolve an agent by name."""

    def __init__(self, name: str, *, known: tuple[str, ...] = ()) -> None:
        self.name = name
        known_msg = ", ".join(sorted(known)) if known else "<none registered>"
        super().__init__(f"no agent registered as {name!r} (known: {known_msg})")


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Discovery metadata for one specialist (ADR-035, A2A-compatible shape).

    ``keywords`` are the routing hints the supervisor's deterministic classifier
    scores against; ``tool_prefixes`` mirror the specialist's allow-list so a
    caller can see the tool surface without invoking the agent. ``model_hint``
    (ADR-052) names the model *tier* this agent prefers — a tier name, never a
    model id, so cards stay deployment-agnostic; empty means no preference.
    ``synthesis_hint`` is the domain's own instruction to any synthesis node
    weaving its results with others' (e.g. "sentiment is estimated, never
    fact") — carried on the card so the synthesizer stays domain-generic and a
    new domain never requires a synthesis-prompt edit; empty means no special
    handling. ``analyze_group`` names the analysis family this domain fans out
    with (e.g. ``"equity"``) — the analyze flow resolves its participant set
    from the registry by group, in registration order, so a new family is pure
    registration; empty means the domain joins no analyze fan-out.
    """

    name: str
    description: str
    tool_prefixes: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)
    version: str = CARD_SCHEMA_VERSION
    model_hint: str = ""
    synthesis_hint: str = ""
    analyze_group: str = ""

    def to_dict(self) -> dict[str, Any]:
        """A2A-shaped card payload for discovery surfaces."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "capabilities": {
                "tool_prefixes": sorted(self.tool_prefixes),
                "keywords": sorted(self.keywords),
                "model_hint": self.model_hint,
                "synthesis_hint": self.synthesis_hint,
                "analyze_group": self.analyze_group,
            },
        }


def card_for_domain(
    spec: DomainSpec,
    *,
    description: str,
    keywords: Iterable[str],
    model_hint: str = "",
    synthesis_hint: str = "",
    analyze_group: str = "",
) -> AgentCard:
    """Build a card from a :class:`DomainSpec` so identity stays single-sourced."""
    return AgentCard(
        name=spec.domain_id,
        description=description,
        tool_prefixes=spec.tool_prefixes,
        keywords=frozenset(k.strip().lower() for k in keywords if k.strip()),
        model_hint=model_hint,
        synthesis_hint=synthesis_hint,
        analyze_group=analyze_group,
    )


class RoutableAgent(Protocol):
    """Anything the supervisor can dispatch to (ADR-051 widening).

    ``SpecialistSubgraph`` satisfies this natively; a
    :class:`~mira.orchestration.foreign.ForeignSpecialist` satisfies it for
    agents behind the public contracts. ``context`` (ADR-052) carries
    per-dispatch state — e.g. ``{"model_tier": ...}`` from a model-tier
    escalation retry — which the specialist scaffold merges into loop state.
    """

    def invoke(
        self,
        query: str,
        *,
        thread_id: str,
        context: Mapping[str, Any] | None = None,
    ) -> SpecialistResult: ...


SpecialistFactory = Callable[[], RoutableAgent]


class AgentCardRegistry:
    """Card-keyed specialist registry — the supervisor's discovery surface.

    Registration pairs a card with a factory (built lazily so registries are
    cheap to declare); ``resolve`` instantiates once and caches.
    """

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}
        self._factories: dict[str, SpecialistFactory] = {}
        self._instances: dict[str, RoutableAgent] = {}

    def register(self, card: AgentCard, factory: SpecialistFactory) -> None:
        """Register ``card`` + specialist ``factory``; later registration overrides."""
        if not card.name:
            raise ValueError("agent card name must be non-empty")
        self._cards[card.name] = card
        self._factories[card.name] = factory
        self._instances.pop(card.name, None)

    def cards(self) -> tuple[AgentCard, ...]:
        """All registered cards in registration order."""
        return tuple(self._cards.values())

    def resolve(self, name: str) -> RoutableAgent:
        """Instantiate (once) and return the specialist registered as ``name``."""
        if name not in self._factories:
            raise UnknownAgentError(name, known=tuple(self._factories))
        if name not in self._instances:
            self._instances[name] = self._factories[name]()
        return self._instances[name]

    def wrap_factories(
        self,
        wrapper: Callable[[AgentCard, SpecialistFactory], SpecialistFactory],
    ) -> None:
        """Replace every factory with ``wrapper(card, factory)`` (ADR-052).

        Registration-time decoration — e.g. wrapping each specialist in a
        model-tier escalating decorator — without touching supervisor code.
        Cached instances are dropped so the wrap applies on next resolve.
        """
        for name, card in self._cards.items():
            self._factories[name] = wrapper(card, self._factories[name])
            self._instances.pop(name, None)

    def match(self, query: str) -> AgentCard | None:
        """Deterministic keyword classification: best card for ``query`` or None.

        Scores each card by distinct keyword hits in the query's word set;
        zero hits → None (the supervisor falls back to its general path). Ties
        resolve to the earliest-registered card so routing is reproducible.
        """
        words = _query_tokens(query)
        best: AgentCard | None = None
        best_score = 0
        for card in self._cards.values():
            score = len(card.keywords & words)
            if score > best_score:
                best, best_score = card, score
        return best


__all__ = [
    "AgentCard",
    "AgentCardRegistry",
    "CARD_SCHEMA_VERSION",
    "RoutableAgent",
    "SpecialistFactory",
    "UnknownAgentError",
    "card_for_domain",
]
