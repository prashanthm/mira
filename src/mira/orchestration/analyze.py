"""Multi-domain analyze graph (ADR-014 follow-on, ADR-015 fan-out shape).

One subject, fanned across every domain registered under an **analysis group**
— a real LangGraph :class:`StateGraph`: one node per participating domain, all
dispatched IN PARALLEL from START, joined at a synthesis node that weaves the
attributed results into grounded prose. Each domain node invokes that domain's
specialist subgraph, so the whole thing is a graph of graphs::

    START ─┬─ technical ────┐
           ├─ fundamental ──┤
           ├─ growth ───────┼─ synthesize ─ END
           ├─ ...           │
           └─ advisor ──────┘

**Groups make the pipeline registration-extensible** (the D3 decision in
claudedocs/multi-domain-synthesis-analysis.md): a card declares
``analyze_group="equity"`` and thereby joins that group's fan-out — the
participant set is resolved from the registry in registration order, never
from a hardcoded list. A new domain family tomorrow (``"health"``, ...) is
pure registration: new cards, same graph builder, same generic synthesizer
(whose per-domain rules travel on the cards as ``synthesis_hint``).

The subject is typed by its group: the equity group's subjects are tickers
(validated + uppercased); an unknown group's subjects are any non-blank
string. Subject *parsing* stays domain-owned — each specialist's inference
extracts what it needs from the query.

Parallel dispatch replaces the sequential ``Supervisor.fan_out`` loop for the
analyze flow (that Phase-B slice remains for routed /turn synthesis). Results
are re-ordered deterministically (registration order) before synthesis so the
prose — and the tests — never depend on thread scheduling.

``analyze_subject`` stays a plain callable (bounded request/response — a
future nightly job can invoke it without event machinery); ``analyze_symbol``
is the equity-group alias. The graph is exposed via
:func:`build_analyze_graph` for inspection/visualization.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.specialists.facets import FACET_DOMAIN_IDS
from mira.orchestration.supervisor import SupervisorResult, _synthesize
from mira.orchestration.synthesis import premortem_analysis, synthesize_analysis
from mira.providers.protocols import ILLMProvider

# The advisor rides along so the equity analyze includes the position/tax read.
ADVISOR_DOMAIN_ID = "advisor"

#: The default analysis group — equities were the first family.
DEFAULT_GROUP = "equity"

#: The canonical equity fan-out order (facets frame the picture, advisor
#: closes it). Kept as documentation and an explicit-domains convenience; the
#: live participant set is resolved from the registry by group.
DEFAULT_ANALYZE_DOMAINS: tuple[str, ...] = (*FACET_DOMAIN_IDS, ADVISOR_DOMAIN_ID)

# Equity subjects are explicit (typed by the caller), so one-letter tickers
# (O, F, T) are unambiguous here — unlike free-text extraction, which stays
# conservative (see specialists.facets.extract_ticker).
_EQUITY_SUBJECT = re.compile(r"[A-Z]{1,6}(\.[A-Z])?")

#: Group -> subject validator/normalizer. A group absent here accepts any
#: non-blank subject verbatim (stripped). Validation is transport hygiene;
#: subject *semantics* belong to the group's domains.
_SUBJECT_RULES: dict[str, tuple[Callable[[str], bool], Callable[[str], str]]] = {
    "equity": (lambda s: bool(_EQUITY_SUBJECT.fullmatch(s.upper())), str.upper),
}


def normalize_subject(subject: str, group: str = DEFAULT_GROUP) -> str | None:
    """The group-typed subject, or None when it fails the group's shape.

    Equity subjects are tickers (2-6 letters, uppercased); groups without a
    registered rule accept any non-blank string as-is.
    """
    sub = (subject or "").strip()
    if not sub:
        return None
    rule = _SUBJECT_RULES.get(group)
    if rule is None:
        return sub
    valid, normalize = rule
    return normalize(sub) if valid(sub) else None


def domains_for_group(registry: AgentCardRegistry, group: str) -> list[str]:
    """The group's participant domains, in registration order."""
    return [card.name for card in registry.cards() if card.analyze_group == group]


def analyze_groups(registry: AgentCardRegistry) -> list[str]:
    """The distinct analysis groups registered, in first-appearance order."""
    seen: list[str] = []
    for card in registry.cards():
        if card.analyze_group and card.analyze_group not in seen:
            seen.append(card.analyze_group)
    return seen


#: |unrealized loss| at/above this makes a case "conflicted" (real money at
#: stake -> deep tier + pre-mortem). Deployment-tunable via env later if needed.
CONFLICT_LOSS_THRESHOLD = 1000.0
#: A firing rule with a scorecard hit rate below this is a weak mandate.
CONFLICT_WEAK_RULE = 0.55


def detect_conflict(results: list[dict[str, Any]]) -> list[str]:
    """Deterministic escalation triggers over the fan-out results (M5).

    Returns the reasons a case is CONFLICTED (empty = routine): a bearish
    signal against an intact thesis, a large unrealized loss at stake, or the
    firing rule having a weak track record. Conflicted cases get the deep
    tier + a pre-mortem; routine cases keep the cheap light-tier path.
    """
    by: dict[str, dict[str, Any]] = {}
    for r in results or []:
        answer = r.get("answer")
        if isinstance(answer, dict):
            by[str(r.get("domain"))] = answer

    reasons: list[str] = []
    decision = _first_decision(by.get("technical", {}))
    action = _first_action(by.get("advisor", {}))
    rec = str((decision or {}).get("recommendation")
              or (action or {}).get("recommendation") or "")
    bearish = rec.startswith("CLOSE") or "SELL" in rec.upper().replace("_CALL", "")

    plan_env = by.get("thesis", {}).get("plan")
    rr = plan_env.get("risk_reward") if isinstance(plan_env, dict) else None
    thesis_intact = bool(
        isinstance(plan_env, dict) and plan_env.get("has_plan")
        and isinstance(rr, dict) and rr.get("status") == "ok"
    )
    if bearish and thesis_intact:
        reasons.append("bearish_signal_vs_intact_thesis")

    detail = (action or {}).get("action_detail") or (decision or {}).get("action_detail")
    loss = (detail or {}).get("unrealized_loss") if isinstance(detail, dict) else None
    try:
        if loss is not None and abs(float(loss)) >= CONFLICT_LOSS_THRESHOLD:
            reasons.append("large_unrealized_loss")
    except (TypeError, ValueError):
        pass

    rule = str((decision or {}).get("rule") or "")
    scorecard = by.get("technical", {}).get("scorecard")
    rows = (scorecard or {}).get("scorecard", {}).get("rules")         if isinstance(scorecard, dict) else None
    for row in rows or []:
        if (isinstance(row, dict) and row.get("rule") == rule
                and isinstance(row.get("hit_rate"), (int, float))
                and row["hit_rate"] < CONFLICT_WEAK_RULE):
            reasons.append("weak_rule_record")
            break
    return reasons


def _first_decision(technical: dict[str, Any]) -> dict[str, Any] | None:
    analysis = technical.get("analysis")
    decisions = analysis.get("decisions") if isinstance(analysis, dict) else None
    return decisions[0] if isinstance(decisions, list) and decisions else None


def _first_action(advisor: dict[str, Any]) -> dict[str, Any] | None:
    actions = advisor.get("actions")
    return actions[0] if isinstance(actions, list) and actions else None


class AnalyzeState(TypedDict, total=False):
    """Graph state: the fan-out query in, accumulated results out.

    ``results`` uses an additive reducer so the parallel domain nodes each
    contribute their attributed answer without clobbering one another.
    """

    query: str
    thread_id: str
    results: Annotated[list[dict[str, Any]], operator.add]
    synthesis: str
    conflict: list[str]


def _query_for(subject: str, question: str | None) -> str:
    """The fan-out query. Each specialist's inference extracts its own subject
    form from this text (e.g. the equity facets regex the ticker out), so the
    normalized subject must appear verbatim."""
    if question and question.strip():
        # Keep the user's words for the synthesis node, but guarantee the
        # subject is present for domain-owned extraction.
        return f"analyze {subject}: {question.strip()}"
    return f"analyze {subject}"


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


def _ordered(results: list[dict[str, Any]], domains: list[str]) -> list[dict[str, Any]]:
    """Results in declaration order — parallel arrival order is scheduling noise."""
    rank = {d: i for i, d in enumerate(domains)}
    return sorted(results, key=lambda r: rank.get(r.get("domain"), len(rank)))


def build_analyze_graph(
    registry: AgentCardRegistry,
    domains: list[str],
    *,
    subject: str,
    question: str | None = None,
    llm: ILLMProvider | None = None,
    context: str | None = None,
):
    """Compile the parallel analyze graph over the given (registered) domains.

    One node per domain — each resolves and invokes its specialist subgraph —
    all edged from START (LangGraph runs same-superstep nodes concurrently),
    joined at ``synthesize``. With no ``llm`` the synthesis node degrades to
    the supervisor's deterministic per-domain concat, preserving the fan-out
    contract offline.
    """
    hints = {card.name: card.synthesis_hint
             for card in registry.cards() if card.synthesis_hint}

    def _domain_node(domain: str) -> Callable[[AnalyzeState], dict[str, Any]]:
        def node(state: AnalyzeState) -> dict[str, Any]:
            specialist = registry.resolve(domain)
            result = specialist.invoke(
                state["query"], thread_id=state["thread_id"]).to_dict()
            return {"results": [result]}

        return node

    def synthesize(state: AnalyzeState) -> dict[str, Any]:
        results = _ordered(state.get("results") or [], domains)
        conflict = detect_conflict(results)
        if llm is None:
            return {"synthesis": _synthesize(results), "conflict": conflict}
        # M5: conflicted cases escalate to the deep tier (thinking, when the
        # routes provide it); routine cases keep the cheap light-tier path.
        return {"conflict": conflict, "synthesis": synthesize_analysis(
            llm, subject, results,
            question=question, context=context, hints=hints,
            tier="deep" if conflict else None)}

    def premortem(state: AnalyzeState) -> dict[str, Any]:
        # M4: the adversarial second pass, ONLY for conflicted cases — the
        # strongest counter-argument from the same facts, appended so the
        # reader sees the bear case for the bull call (and vice versa).
        conflict = state.get("conflict") or []
        draft = state.get("synthesis") or ""
        if llm is None or not conflict or not draft:
            return {}
        counter = premortem_analysis(
            llm, subject, _ordered(state.get("results") or [], domains), draft)
        if not counter:
            return {}
        tags = ", ".join(conflict)
        return {"synthesis": f"{draft}\n\n**Pre-mortem** ({tags}): {counter}"}

    graph = StateGraph(AnalyzeState)
    graph.add_node("synthesize", synthesize)
    graph.add_node("premortem", premortem)
    for domain in domains:
        graph.add_node(domain, _domain_node(domain))
        graph.add_edge(START, domain)
        graph.add_edge(domain, "synthesize")
    graph.add_edge("synthesize", "premortem")
    graph.add_edge("premortem", END)
    return graph.compile()


def analyze_subject(
    registry: AgentCardRegistry,
    subject: str,
    *,
    group: str = DEFAULT_GROUP,
    question: str | None = None,
    domains: tuple[str, ...] | None = None,
    thread_id: str | None = None,
    llm: ILLMProvider | None = None,
    context: str | None = None,
) -> SupervisorResult:
    """Fan one subject across its group's registered domains in parallel, then
    synthesize.

    The participant set is the registry's ``analyze_group == group`` cards in
    registration order (an explicit ``domains`` tuple overrides — the
    cross-group escape hatch). Returns a :class:`SupervisorResult` whose
    ``results`` carry one attributed answer per domain. When ``llm`` is
    supplied, ``synthesis`` is grounded multi-domain prose; otherwise it stays
    the deterministic concat. ``question`` (the user's words) is folded into
    the fan-out query and passed to synthesis; ``context`` is optional prior
    conversation for follow-ups.
    """
    sub = normalize_subject(subject, group) or (subject or "").strip()
    if domains is not None:
        active = _registered(registry, domains)
    else:
        active = domains_for_group(registry, group)
    query = _query_for(sub, question)
    thread = thread_id or f"analyze-{group}-{sub}"
    if not active:
        # Nothing registered for the group (no MCP tools discovered): return
        # an empty, well-formed result rather than raising.
        return SupervisorResult(query=query, routed_domain=None, results=[], synthesis="")

    app = build_analyze_graph(
        registry, active, subject=sub, question=question, llm=llm, context=context)
    state = app.invoke({"query": query, "thread_id": thread, "results": []})
    results = _ordered(state.get("results") or [], active)
    return SupervisorResult(
        query=query,
        routed_domain=None,
        results=results,
        synthesis=state.get("synthesis") or "",
    )


def analyze_symbol(
    registry: AgentCardRegistry,
    symbol: str,
    *,
    question: str | None = None,
    domains: tuple[str, ...] | None = None,
    thread_id: str | None = None,
    llm: ILLMProvider | None = None,
    context: str | None = None,
) -> SupervisorResult:
    """Equity-group alias of :func:`analyze_subject` (tickers as subjects)."""
    return analyze_subject(
        registry, symbol, group="equity", question=question,
        domains=domains, thread_id=thread_id, llm=llm, context=context,
    )


def cached_analyze_provider(
    registry: AgentCardRegistry,
    *,
    llm: ILLMProvider | None = None,
    group: str = DEFAULT_GROUP,
) -> Callable[[str, str | None, bool], dict[str, Any] | None]:
    """In-memory ``{subject: analyze-result}`` cache over :func:`analyze_subject`.

    ``provider(subject, question, refresh)`` returns the fan-out result dict
    for a group-valid subject (generated lazily; ``refresh`` forces
    regeneration). A question makes the entry question-specific so follow-ups
    aren't served a stale answer. ``llm`` (when supplied) drives grounded
    synthesis. Returns None only for a subject that fails the group's shape.
    """
    cache: dict[str, dict[str, Any]] = {}

    def provider(subject: str, question: str | None = None, refresh: bool = False) -> dict[str, Any] | None:
        sub = normalize_subject(subject, group)
        if sub is None:
            return None
        key = f"{group}::{sub}::{(question or '').strip()}"
        if refresh or key not in cache:
            cache[key] = analyze_subject(
                registry, sub, group=group, question=question, llm=llm).to_dict()
        return cache[key]

    return provider


__all__ = [
    "ADVISOR_DOMAIN_ID",
    "DEFAULT_ANALYZE_DOMAINS",
    "DEFAULT_GROUP",
    "AnalyzeState",
    "analyze_groups",
    "analyze_subject",
    "analyze_symbol",
    "build_analyze_graph",
    "cached_analyze_provider",
    "domains_for_group",
    "normalize_subject",
]
