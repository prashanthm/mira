"""Multi-facet analyze flow (ADR-014 follow-on) — fan-out over the facet graph.

One ticker, fanned across the analysis facets (technical, fundamental, news) plus
the advisor (position/tax), each grounded in its Vantage tool. This is the
"multi-faceted analysis" the notebook asks for: instead of one tool answering
"what should I do about SYM?", every facet reads its slice and the results are
collected for a synthesis node (Step 4) to weave into grounded prose.

Built as a plain **callable** (``analyze_symbol``) over ``Supervisor.fan_out`` —
NOT an event bus. The flow is bounded request/response; a future nightly job
could invoke the same callable (the deferred scheduler door) without any event
machinery. Domains are filtered to those actually registered, so a facet whose
tool failed to bridge simply drops out rather than crashing the fan-out
(``registry.resolve`` raises on an unknown domain).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.specialists.facets import FACET_DOMAIN_IDS
from mira.orchestration.supervisor import Supervisor, SupervisorResult
from mira.orchestration.synthesis import synthesize_analysis
from mira.providers.protocols import ILLMProvider

# The advisor rides along so the analyze read includes the position/tax facet.
ADVISOR_DOMAIN_ID = "advisor"

#: Default fan-out order: the three analysis facets, then the advisor.
DEFAULT_ANALYZE_DOMAINS: tuple[str, ...] = (*FACET_DOMAIN_IDS, ADVISOR_DOMAIN_ID)

_TICKER = re.compile(r"\b[A-Z]{2,6}\b")


def _query_for(symbol: str, question: str | None) -> str:
    """The fan-out query. Each facet extracts the ticker and calls its tool; the
    ticker must appear uppercase so the facet inference finds it."""
    sym = symbol.upper().strip()
    if question and question.strip():
        # Keep the user's words for the synthesis node, but guarantee the ticker
        # is present uppercase for facet inference.
        return f"analyze {sym}: {question.strip()}"
    return f"analyze {sym}"


def _registered(registry: AgentCardRegistry, domains: tuple[str, ...]) -> list[str]:
    """Filter to domains with a registered card, preserving order (no duplicates)."""
    known = {card.name for card in registry.cards()}
    seen: set[str] = set()
    out: list[str] = []
    for d in domains:
        if d in known and d not in seen:
            out.append(d)
            seen.add(d)
    return out


def analyze_symbol(
    registry: AgentCardRegistry,
    symbol: str,
    *,
    question: str | None = None,
    domains: tuple[str, ...] = DEFAULT_ANALYZE_DOMAINS,
    thread_id: str | None = None,
    llm: ILLMProvider | None = None,
    context: str | None = None,
) -> SupervisorResult:
    """Fan one ticker across the (registered) facet + advisor domains, then synthesize.

    Returns a :class:`SupervisorResult` whose ``results`` carry one attributed
    answer per facet. When ``llm`` is supplied, ``synthesis`` is grounded
    multi-facet prose from the synthesis node (the fix for terse answers);
    otherwise it stays the deterministic concat. ``question`` (the user's words)
    is both folded into the fan-out query and passed to synthesis; ``context`` is
    optional prior conversation for follow-ups.
    """
    sym = symbol.upper().strip()
    active = _registered(registry, domains)
    supervisor = Supervisor(registry)
    query = _query_for(sym, question)
    thread = thread_id or f"analyze-{sym}"
    if not active:
        # Nothing registered (no MCP tools discovered): return an empty,
        # well-formed result rather than raising.
        return SupervisorResult(query=query, routed_domain=None, results=[], synthesis="")
    result = supervisor.fan_out(query, active, thread_id=thread)
    if llm is not None:
        result.synthesis = synthesize_analysis(
            llm, sym, result.results, question=question, context=context
        )
    return result


def cached_analyze_provider(
    registry: AgentCardRegistry,
    *,
    llm: ILLMProvider | None = None,
) -> Callable[[str, str | None, bool], dict[str, Any] | None]:
    """In-memory ``{symbol: analyze-result}`` cache over :func:`analyze_symbol`.

    ``provider(symbol, question, refresh)`` returns the fan-out result dict for a
    symbol (generated lazily; ``refresh`` forces regeneration). A question makes
    the entry question-specific so follow-ups aren't served a stale answer.
    ``llm`` (when supplied) drives grounded synthesis. Returns None only for a
    blank/invalid symbol.
    """
    cache: dict[str, dict[str, Any]] = {}

    def provider(symbol: str, question: str | None = None, refresh: bool = False) -> dict[str, Any] | None:
        sym = (symbol or "").upper().strip()
        if not sym or not _TICKER.fullmatch(sym):
            return None
        key = f"{sym}::{(question or '').strip()}"
        if refresh or key not in cache:
            cache[key] = analyze_symbol(registry, sym, question=question, llm=llm).to_dict()
        return cache[key]

    return provider


__all__ = [
    "ADVISOR_DOMAIN_ID",
    "DEFAULT_ANALYZE_DOMAINS",
    "analyze_symbol",
    "cached_analyze_provider",
]
