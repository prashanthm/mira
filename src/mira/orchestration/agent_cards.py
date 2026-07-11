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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from mira.orchestration.specialist_scaffold import DomainSpec, SpecialistResult

_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]*")

CARD_SCHEMA_VERSION = "1"


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
    caller can see the tool surface without invoking the agent.
    """

    name: str
    description: str
    tool_prefixes: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)
    version: str = CARD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """A2A-shaped card payload for discovery surfaces."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "capabilities": {
                "tool_prefixes": sorted(self.tool_prefixes),
                "keywords": sorted(self.keywords),
            },
        }


def card_for_domain(
    spec: DomainSpec,
    *,
    description: str,
    keywords: Iterable[str],
) -> AgentCard:
    """Build a card from a :class:`DomainSpec` so identity stays single-sourced."""
    return AgentCard(
        name=spec.domain_id,
        description=description,
        tool_prefixes=spec.tool_prefixes,
        keywords=frozenset(k.strip().lower() for k in keywords if k.strip()),
    )


class RoutableAgent(Protocol):
    """Anything the supervisor can dispatch to (ADR-051 widening).

    ``SpecialistSubgraph`` satisfies this natively; a
    :class:`~mira.orchestration.foreign.ForeignSpecialist` satisfies it for
    agents behind the public contracts.
    """

    def invoke(self, query: str, *, thread_id: str) -> SpecialistResult: ...


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

    def match(self, query: str) -> AgentCard | None:
        """Deterministic keyword classification: best card for ``query`` or None.

        Scores each card by distinct keyword hits in the query's word set;
        zero hits → None (the supervisor falls back to its general path). Ties
        resolve to the earliest-registered card so routing is reproducible.
        """
        words = set(_WORD.findall(query.lower()))
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
