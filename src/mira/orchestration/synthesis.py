"""LLM synthesis over multi-domain analyze results — the fix for terse answers.

The deterministic ``supervisor._synthesize`` concatenates ``[domain] {json}`` —
which is why "what should I do about INDA?" surfaced a bare "MONITOR". This node
takes the fan-out results + the user's question + optional conversation context
and asks an LLM to weave them into **grounded multi-domain prose**, under a
strict, DOMAIN-GENERIC system prompt: synthesize ONLY what the tools returned,
cite the domain a claim came from, and NEVER invent a number the tools didn't
provide. Domain-specific rules ("sentiment is estimated", "weigh close calls
against the stored thesis") are NOT written here — each domain carries its own
``synthesis_hint`` on its :class:`~mira.orchestration.agent_cards.AgentCard`,
and only hints for domains present in the results reach the prompt.

Model selection rides the ADR-052 tier plane: synthesis asks for the ``deep``
tier and playbook polish the ``light`` tier, so the gateway's router (via
``MODEL_ROUTES``) picks the concrete model — no per-task env knobs. The
composition root passes an agent-bound gateway view (``gateway.for_agent``)
whose ``chat`` threads the tier; a plain provider without ``chat`` (or without
a ``tier`` parameter) still works, it just uses its configured default model.

Fail-safe: with no LLM (or an LLM error), synthesis falls back to a deterministic
**readable** digest of the facets — still far better than raw JSON, and it never
fabricates. So the node degrades, it never blanks the answer.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from typing import Any

from mira.model.tiering import ModelTier
from mira.providers.protocols import ILLMProvider

#: Tier requested per synthesis task (ADR-052). Facet grounding is deterministic
#: tool calls (no LLM); weaving them into decision-useful prose is the hard,
#: quality-sensitive step — so synthesis asks for the deep tier. Playbook polish
#: only rewrites an already-correct templated draft — light is plenty.
SYNTHESIS_TIER = ModelTier.LIGHT.value
PLAYBOOK_TIER = ModelTier.LIGHT.value


def _invoke(llm: ILLMProvider, system: str, user: str, *, tier: str) -> str:
    """One system+user chat turn, tier-routed when the provider supports it.

    An agent-bound gateway view exposes ``chat(messages, tier=...)`` — the tier
    reaches the router and picks the model. A bare provider ``chat`` without a
    ``tier`` parameter is called without it; a provider with no ``chat`` at all
    degrades to ``complete`` over the concatenated prompt. Exceptions propagate
    (call sites own the fallback contract).
    """
    chat = getattr(llm, "chat", None)
    if chat is None:
        return str(llm.complete(f"{system}\n\n{user}") or "").strip()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {}
    try:
        if "tier" in inspect.signature(chat).parameters:
            kwargs["tier"] = tier
    except (TypeError, ValueError):  # builtins/uninspectable callables: skip tier
        pass
    reply = chat(messages, **kwargs)
    return str(getattr(reply, "text", "") or "").strip()

# The GENERIC synthesis contract — domain-agnostic on purpose. Anything a
# domain needs said about ITS results ("sentiment is estimated", "weigh calls
# against the stored thesis") travels on that domain's AgentCard as
# ``synthesis_hint`` and is assembled into the prompt below only when the
# domain actually returned results. A new domain never edits this module.
_SYSTEM_PROMPT = (
    "You synthesize grounded specialist DOMAIN results into a concise, "
    "decision-useful answer.\n"
    "HARD RULES:\n"
    "1. Only facts from the domain results — never invent numbers, dates, or "
    "recommendations.\n"
    "2. Name the source domain for every figure or call.\n"
    "3. Empty/tool_error/null domains: say so plainly.\n"
    "4. Cover every domain with data; end with a one-line net takeaway. No "
    "preamble. Keep the whole synthesis under 250 words."
)


def _guidance_block(
    results: list[dict[str, Any]],
    hints: Mapping[str, str] | None,
) -> str:
    """The per-domain guidance lines for domains that are actually present.

    Empty when no present domain carries a hint — the core prompt never
    references guidance, so nothing dangles.
    """
    if not hints:
        return ""
    present = [r.get("domain") for r in results or []
               if _has_data(_trim(r.get("answer") if isinstance(r.get("answer"), Mapping) else {}))]
    lines = [f"- {d}: {hints[d].strip()}"
             for d in present if hints.get(d, "").strip()]
    if not lines:
        return ""
    return ("DOMAIN GUIDANCE (each line is that domain's own HARD RULE for "
            "how its results may be used):\n" + "\n".join(lines))

_MAX_FACET_JSON = 450  # cap each facet digest so the prompt stays bounded


def _facet_digest(results: list[dict[str, Any]]) -> str:
    """A compact, labeled digest of each facet answer for the prompt.

    Keeps the structure the model needs (facet name + its grounded answer) while
    trimming oversize payloads (e.g. full bar arrays) so the context stays small.
    Errors are kept VISIBLE so the model reports them instead of guessing.
    """
    blocks: list[str] = []
    for result in results or []:
        domain = result.get("domain", "?")
        if result.get("error"):
            blocks.append(f"### {domain}\nERROR: {result['error']}")
            continue
        answer = result.get("answer")
        answer = answer if isinstance(answer, Mapping) else {}
        trimmed = _trim(answer)
        if not _has_data(trimmed):
            blocks.append(f"### {domain}\nno_data")
            continue
        blocks.append(f"### {domain}\n{json.dumps(trimmed, sort_keys=True, default=str)}")
    return "\n\n".join(blocks)


def _has_data(value: Any) -> bool:
    """True when a trimmed digest carries any informative (non-null, non-flag)
    value — a payload of nulls and no_data markers digests to one line."""
    if isinstance(value, Mapping):
        return any(_has_data(v) for k, v in value.items()
                   if k not in ("facet", "symbol", "no_data", "no_news", "has_plan"))
    if isinstance(value, list):
        return any(_has_data(v) for v in value)
    if isinstance(value, bool):
        return False
    return value not in (None, "", {})


def _trim(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Structure each digest to fit the cap: the cap sets the token bound,
    structural trims decide WHAT survives it — decision cores instead of
    evidence trees, tax/wash essentials instead of full action payloads.
    Truncation is the last resort, not the mechanism."""
    out = _strip_envelope(dict(answer))
    # The technical facet nests bars under levels.bars — heavy and unneeded for
    # synthesis (the model reasons over the computed levels, not raw OHLCV).
    levels = out.get("levels")
    if isinstance(levels, Mapping) and "bars" in levels:
        levels = dict(levels)
        levels["bars"] = f"<{len(levels['bars'])} bars omitted>"
        out["levels"] = levels
    # Decision journal (technical facet) and advisor actions both carry full
    # per-timeframe evidence trees per decision; synthesis reasons over the
    # decision CORE — recommendation, rule, rationale, conviction, nearest
    # levels, tax/wash math.
    analysis = out.get("analysis")
    if isinstance(analysis, Mapping) and isinstance(analysis.get("decisions"), list):
        analysis = dict(analysis)
        analysis["decisions"] = [
            _decision_core(d) if isinstance(d, Mapping) else d
            for d in analysis["decisions"]
        ]
        out["analysis"] = analysis
    if isinstance(out.get("actions"), list):
        out["actions"] = [
            _decision_core(a) if isinstance(a, Mapping) else a
            for a in out["actions"]
        ]
    # Expectations: the implied bar + assumptions are the content; scenarios
    # only restate them as a ladder.
    expectations = out.get("expectations")
    if isinstance(expectations, Mapping) and expectations.get("scenarios"):
        expectations = dict(expectations)
        expectations.pop("scenarios", None)
        out["expectations"] = expectations
    # Thesis: the plan is the content; journal entries are history.
    plan = out.get("plan")
    if isinstance(plan, Mapping) and plan.get("journal"):
        plan = dict(plan)
        plan.pop("journal", None)
        out["plan"] = plan
    # News: top 3 headlines, headline fields only.
    news = out.get("news")
    inner = news.get("news") if isinstance(news, Mapping) else None
    if isinstance(inner, Mapping) and isinstance(inner.get("items"), list):
        news, inner = dict(news), dict(inner)
        inner["items"] = [
            {k: it.get(k) for k in ("title", "publisher", "published")}
            if isinstance(it, Mapping) else it
            for it in inner["items"][:3]
        ]
        news["news"] = inner
        out["news"] = news
    blob = json.dumps(out, default=str)
    if len(blob) > _MAX_FACET_JSON:
        return {"_truncated": blob[:_MAX_FACET_JSON]}
    return out


_ENVELOPE_KEYS = ("provenance", "as_of", "source", "stale")


def _strip_envelope(value):
    """Digest-only copy without transport envelope keys (attribution stays on
    the API result; the prompt never cites source_id strings)."""
    if isinstance(value, Mapping):
        return {k: _strip_envelope(v) for k, v in value.items()
                if k not in _ENVELOPE_KEYS}
    if isinstance(value, list):
        return [_strip_envelope(v) for v in value]
    return value


def _decision_core(decision: Mapping[str, Any]) -> dict[str, Any]:
    """A journal decision/action minus its evidence tree, keeping the nearest
    levels and the full action math (wash/loss/credit — decision-critical)."""
    core = {k: v for k, v in decision.items() if k not in ("evidence", "leg_actions")}
    evidence = decision.get("evidence")
    if isinstance(evidence, Mapping):
        for key in ("nearest_support", "nearest_resistance",
                    "broke_support_with_momentum", "at_support"):
            if key in evidence:
                core[key] = evidence[key]
    legs = decision.get("leg_actions")
    if isinstance(legs, list) and legs:
        core["leg_actions"] = [
            {k: leg.get(k) for k in ("occ_symbol", "action", "rationale")}
            if isinstance(leg, Mapping) else leg
            for leg in legs
        ]
    return core


def _fallback(symbol: str, results: list[dict[str, Any]]) -> str:
    """Deterministic readable digest when no LLM is available — never fabricates.

    One line per facet naming what it returned (recommendation, valuation head,
    news lean), so even offline the answer beats raw ``[domain] {json}``.
    """
    lines = [f"Multi-facet read for {symbol} (deterministic — no synthesis model):"]
    for result in results or []:
        domain = result.get("domain", "?")
        if result.get("error"):
            lines.append(f"- {domain}: error — {result['error']}")
            continue
        answer = result.get("answer") if isinstance(result.get("answer"), Mapping) else {}
        lines.append(f"- {domain}: {_one_line(domain, answer)}")
    return "\n".join(lines)


def _one_line(domain: str, answer: Mapping[str, Any]) -> str:
    """A short human line for one facet answer (best-effort, structural)."""
    if answer.get("status") == "tool_error":
        return f"tool error ({answer.get('tool', '?')})"
    if domain == "technical":
        analysis = answer.get("analysis")
        if isinstance(analysis, Mapping):
            decisions = analysis.get("decisions")
            if isinstance(decisions, list) and decisions:
                d = decisions[0]
                if isinstance(d, Mapping):
                    return f"recommendation {d.get('recommendation', '?')} ({d.get('rule', '?')})"
        return "no decision journal entry"
    if domain == "fundamental":
        fund = answer.get("fundamentals")
        inner = fund.get("fundamentals") if isinstance(fund, Mapping) else None
        if isinstance(inner, Mapping):
            pe = inner.get("pe")
            target = inner.get("target_mean")
            return f"P/E {pe if pe is not None else 'n/a'}, mean target {target if target is not None else 'n/a'}"
        return "no fundamentals"
    if domain == "news":
        news = answer.get("news")
        inner = news.get("news") if isinstance(news, Mapping) else None
        line = "no news"
        if isinstance(inner, Mapping):
            items = inner.get("items") or []
            sent = inner.get("sentiment") or {}
            band = sent.get("band", "?") if isinstance(sent, Mapping) else "?"
            line = f"{len(items)} headline(s), sentiment lean {band} (estimated)"
        earn = answer.get("earnings")
        cal = earn.get("earnings") if isinstance(earn, Mapping) else None
        if isinstance(cal, Mapping):
            if cal.get("days_until") is not None:
                line += f"; earnings {cal.get('next_date')} in {cal['days_until']}d"
            elif not cal.get("future_date_known", False):
                line += "; next earnings date unknown"
        return line
    if domain == "growth":
        grown = answer.get("growth")
        inner = grown.get("growth") if isinstance(grown, Mapping) else None
        if isinstance(inner, Mapping):
            yoy = inner.get("revenue_yoy")
            fcfm = inner.get("fcf_margin")
            r40 = inner.get("rule_of_40")
            yoy_s = f"{yoy * 100:.0f}%" if yoy is not None else "n/a"
            fcf_s = f"{fcfm * 100:.0f}%" if fcfm is not None else "n/a"
            r40_s = f"{r40:.0f}" if r40 is not None else "n/a"
            return f"revenue YoY {yoy_s}, FCF margin {fcf_s}, Rule of 40 {r40_s}"
        return "no growth data"
    if domain == "expectations":
        implied = answer.get("expectations", {}).get("implied") \
            if isinstance(answer.get("expectations"), Mapping) else None
        assumptions = answer.get("expectations", {}).get("assumptions") \
            if isinstance(answer.get("expectations"), Mapping) else None
        if isinstance(implied, Mapping):
            status = implied.get("status")
            if status == "negative_fcf":
                return "implied growth undefined: negative FCF"
            g = implied.get("fcf_growth_10y")
            if status == "ok" and g is not None:
                a = assumptions if isinstance(assumptions, Mapping) else {}
                return (f"market implies ~{g * 100:.0f}% FCF growth "
                        f"(r={a.get('discount_rate', '?')}, "
                        f"gt={a.get('terminal_growth', '?')})")
            return f"no implied growth ({status})"
        return "no expectations data"
    if domain == "thesis":
        plan_env = answer.get("plan")
        if isinstance(plan_env, Mapping):
            plan = plan_env.get("plan")
            if plan_env.get("has_plan") and isinstance(plan, Mapping):
                return (f"plan on file: target {plan.get('target', 'n/a')} / "
                        f"stop {plan.get('stop', 'n/a')}, "
                        f"updated {str(plan.get('updated_at', '?'))[:10]}")
            return "no thesis on file"
        return "no thesis data"
    # advisor / other: surface a recommendation if present, else compact json.
    for key in ("recommendation", "actions", "recommendations"):
        if key in answer:
            return f"{key}: {json.dumps(answer[key], default=str)[:160]}"
    return json.dumps(dict(answer), sort_keys=True, default=str)[:160]


def synthesize_analysis(
    llm: ILLMProvider | None,
    symbol: str,
    results: list[dict[str, Any]],
    *,
    question: str | None = None,
    context: str | None = None,
    hints: Mapping[str, str] | None = None,
) -> str:
    """Weave fan-out ``results`` into grounded multi-domain prose via the LLM.

    ``llm`` None (or any LLM failure) → the deterministic :func:`_fallback`.
    ``question`` is the user's actual ask; ``context`` is optional prior
    conversation (so "what do you mean?" follow-ups have grounding). ``hints``
    maps domain id → that domain's card-carried ``synthesis_hint``; only hints
    for domains present in ``results`` reach the prompt, so the synthesizer
    stays domain-generic.
    """
    if not results:
        return f"No analysis domains returned results for {symbol}."
    if llm is None:
        return _fallback(symbol, results)

    ask = question.strip() if question and question.strip() else f"What should I do about {symbol}?"
    system = _SYSTEM_PROMPT
    guidance = _guidance_block(results, hints)
    if guidance:
        system = f"{system}\n\n{guidance}"
    user_parts = [f"User question ({symbol}): {ask}"]
    if context and context.strip():
        user_parts.append(f"Prior conversation:\n{context.strip()}")
    user_parts.append("Domain results:\n" + _facet_digest(results))
    user_prompt = "\n\n".join(user_parts)

    try:
        text = _invoke(llm, system, user_prompt, tier=SYNTHESIS_TIER)
        return text or _fallback(symbol, results)
    except Exception:  # noqa: BLE001 — any LLM/adapter failure degrades, never blanks
        return _fallback(symbol, results)


# ============================================================ 0DTE SPX playbook

_PLAYBOOK_SYSTEM_PROMPT = (
    "You rewrite a deterministic 0DTE SPX options playbook into plain, simple "
    "English a busy trader reads in 30 seconds. You are given a TEMPLATED DRAFT "
    "(already correct) and the raw SCAFFOLD it came from.\n\n"
    "HARD RULES:\n"
    "1. Use ONLY numbers present in the draft/scaffold. NEVER invent or change a "
    "level, strike, date, or percentage. If it's not in the data, don't say it.\n"
    "2. Keep every setup CONDITIONAL and tied to its trigger level (\"if SPX holds "
    "above 7481 ...\"). Never turn it into a bare \"buy calls now.\"\n"
    "3. Lead with the one-line regime read (gamma + the day's catalyst if any). "
    "Then the key levels to watch, then the 2-3 setups in the trader's own terms, "
    "then a short 'what to watch' line.\n"
    "4. Simple words. Short sentences. No jargon the draft didn't already use; if "
    "you use a term like 'gamma flip' or 'put wall', say in a few words what it "
    "means the first time.\n"
    "5. Keep it tight — aim for ~150-220 words. Preserve the caveats at the end "
    "verbatim in one short line (0DTE-blind, context-not-a-signal, not advice)."
)


def _fmt_num(v) -> str:
    try:
        f = float(v)
        return f"{f:.0f}" if abs(f - round(f)) < 0.05 else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(v)


def playbook_template(scaffold: Mapping[str, Any]) -> str:
    """Deterministic plain-text playbook from the scaffold — the ground truth and
    the fallback when no LLM is available. Never fabricates: every line is a
    scaffold value. Mira's LLM polish rewrites THIS into simpler prose."""
    reg = scaffold.get("regime") or {}
    lines: list[str] = []
    sess = scaffold.get("session", "next session")
    lines.append(f"0DTE SPX playbook for {sess}.")

    # regime line
    bits = []
    if reg.get("gamma"):
        bits.append(f"dealer gamma is {reg['gamma']}")
    if reg.get("spot") is not None:
        bits.append(f"spot ~{_fmt_num(reg['spot'])}")
    if reg.get("vix") is not None:
        bits.append(f"VIX {_fmt_num(reg['vix'])}"
                    + (f" ({reg['vix_band']})" if reg.get("vix_band") else ""))
    if reg.get("vwap_regime"):
        bits.append(reg["vwap_regime"])
    if bits:
        lines.append("Regime: " + ", ".join(bits) + ".")

    # catalyst
    cat = scaffold.get("catalysts") or {}
    if cat.get("today"):
        lines.append(f"Catalyst TODAY: {cat['today']} — expect bigger moves, size down.")
    elif cat.get("next_session"):
        lines.append(f"Catalyst next session: {cat['next_session']}.")
    opex = scaffold.get("opex") or {}
    if opex.get("today_is_triple_witching"):
        lines.append("Triple-witching OpEx today — gamma rolls off, regime can shift after.")

    # key levels (top of the ladder around spot)
    ladder = scaffold.get("level_ladder") or []
    if ladder:
        lines.append("Key levels: " + " · ".join(
            f"{_fmt_num(r['price'])} ({r['kind']})" for r in ladder[:8]) + ".")

    # setups
    for i, su in enumerate(scaffold.get("setups") or [], 1):
        trig = su.get("trigger", ""); struct = su.get("structure", "")
        lines.append(f"Setup {i} — {trig}: {struct}")

    # a lookback edge if present
    edge = ((scaffold.get("edges") or {}).get("gex_regime_next_day_range") or {})
    if edge.get("read"):
        lines.append("Lookback: " + edge["read"])

    for c in scaffold.get("caveats") or []:
        lines.append(c)
    return "\n".join(lines)


def synthesize_playbook(
    llm: ILLMProvider | None,
    scaffold: Mapping[str, Any],
    *,
    context: str | None = None,
) -> str:
    """Plain-English 0DTE SPX playbook: templated draft → LLM polish.

    The templated draft is always the ground truth; the LLM only rewrites it into
    simpler prose (same numbers, same conditional setups). ``llm`` None or any LLM
    failure returns the templated draft unchanged — it never blanks, never
    fabricates."""
    draft = playbook_template(scaffold)
    if llm is None:
        return draft

    user_parts = ["TEMPLATED DRAFT (rewrite this into simple prose — keep all numbers):",
                  draft]
    if context and context.strip():
        user_parts.append(f"Extra context:\n{context.strip()}")
    # the scaffold as JSON so the model can see structure, but the draft is authoritative
    user_parts.append("Raw scaffold (reference only; the draft is authoritative):\n"
                      + json.dumps(_trim_scaffold(scaffold), default=str)[:2000])
    user_prompt = "\n\n".join(user_parts)

    try:
        text = _invoke(llm, _PLAYBOOK_SYSTEM_PROMPT, user_prompt, tier=PLAYBOOK_TIER)
        return text or draft
    except Exception:  # noqa: BLE001 — degrade to the templated draft, never blank
        return draft


def _trim_scaffold(scaffold: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the heaviest keys so the reference JSON stays bounded."""
    out = dict(scaffold)
    chart = out.get("chart")
    if isinstance(chart, Mapping):
        out["chart"] = {k: v for k, v in chart.items() if k not in ("resistance", "support")}
    return out


__all__ = [
    "PLAYBOOK_TIER",
    "SYNTHESIS_TIER",
    "playbook_template",
    "synthesize_analysis",
    "synthesize_playbook",
]
