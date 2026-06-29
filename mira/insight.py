"""Run the panel and persist a structured InsightReport."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

import json as _json

from .llm import OllamaUnavailable, build_model
from .panel import build_insight_panel, build_simple_agent, report_request
from .providers.base import DataProvider
from .schema import InsightReport
from .tools import _summarize, make_tools

log = logging.getLogger("mira.insight")


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model's text (handles ```json fences + prose)."""
    if not text:
        return None
    # fenced block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [m.group(1)] if m else []
    # then the largest brace-balanced span
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


_REFORMAT_PROMPT = """Convert the analysis below into a single JSON object with EXACTLY these keys:
- summary: string (2-3 sentences)
- what_worked: array of objects {topic, detail, evidence}
- what_didnt: array of objects {topic, detail, evidence}
- adjustments: array of strings (advisory suggestions)
- memory_decisions: array of objects, one per durable LESSON worth remembering. Each is either
  {"reinforce": "<existing lesson id like L-001>", "evidence": "..."} when today repeats a known
  lesson, OR {"new_text": "the lesson", "category": "equity-trend|options-structure|regime|risk|execution|other", "evidence": "..."} for a new one.
- confidence: one of "low" | "medium" | "high"
- caveats: string

Output ONLY the JSON object — no prose, no markdown fences. Use [] for empty arrays.

ANALYSIS:
"""


def _structure_via_reformat(chat, analysis: str) -> InsightReport | None:
    """Ask the model to reformat free-form analysis into the InsightReport schema.

    A plain (non-agentic) call — local models do this reliably even when they ignore
    structured-output tool-calling. Returns None if it still can't be parsed.
    """
    if not analysis or not analysis.strip():
        return None
    try:
        resp = chat.invoke(_REFORMAT_PROMPT + analysis[:6000])
        txt = getattr(resp, "content", "") or ""
        data = _extract_json(txt)
        if data:
            return InsightReport(**data)
    except Exception as e:
        log.info(f"reformat step failed ({e}); falling back to text extraction.")
    return None


def _coerce_report(data: dict | None, raw_text: str) -> InsightReport:
    """Best-effort coercion to an InsightReport; never throws (local models are messy)."""
    if data:
        try:
            return InsightReport(**data)
        except Exception as e:
            log.info(f"InsightReport coercion failed ({e}); wrapping raw text.")
    return InsightReport(
        summary=(raw_text or "No structured insight produced.").strip()[:1200],
        confidence="low",
        caveats="Model did not return clean structured JSON; summary holds the raw analysis.",
    )


def _preloaded_request(provider: DataProvider) -> str:
    """Build a single request with the compact data inlined — minimizes tool round-trips
    for the simple/local mode (the agent can still call tools for more if it wants)."""
    blocks = []
    for res in provider.resources():
        try:
            data = provider.read(res, limit=40)
        except Exception:
            continue
        blocks.append(f"### {res}\n{_summarize(data)}")
    data_text = "\n\n".join(blocks)
    return report_request() + "\n\nHere is the data:\n\n" + data_text


def _lessons_context(lessons_path: str | None) -> str:
    """Render the active lessons memory for the prompt (so the agent can reinforce by id)."""
    if not lessons_path:
        return ""
    from .memory import active, load_lessons
    ls = active(load_lessons(lessons_path))
    if not ls:
        return ("\n\nThe lessons memory is EMPTY. Do NOT use 'reinforce' (there is nothing to "
                "reinforce). For each durable lesson from today's data, emit a memory_decision "
                "with 'new_text' (the lesson) and 'category'. Aim for 1-3 concrete lessons.")
    lines = [f"- {l.id} [{l.category}] (seen {l.occurrences}x): {l.text}" for l in ls]
    return (
        "\n\nExisting lessons memory (reinforce by id if today repeats one, else add new):\n"
        + "\n".join(lines)
    )


def run_panel(provider: DataProvider, model: str = "qwen2.5:7b",
              base_url: str = "http://localhost:11434",
              out_path: str = "options_insights.jsonl",
              subagent_settings: dict | None = None,
              mode: str = "simple",
              lessons_path: str | None = None,
              stale_days: int = 30) -> dict:
    """Generate one insight + curate the lessons memory via the local agent; append to out_path.

    mode="simple" (default): one deep agent with the compact data pre-loaded — fast and
    reliable on local hardware. mode="panel": the full sub-agent research panel (opt-in).

    If lessons_path is set, the agent reads the durable lessons memory and decides, per
    observation, to reinforce an existing lesson (by id) or add a new one; the result is
    folded back in (occurrences++ / append) and stale lessons retire — the learning loop.

    Returns the recorded record. Raises OllamaUnavailable if the local LLM is down.
    """
    chat = build_model(model=model, base_url=base_url)  # raises OllamaUnavailable if down
    tools = make_tools(provider, lessons_path=lessons_path)

    if mode == "panel":
        agent = build_insight_panel(chat, tools, subagent_model_settings=subagent_settings)
        request = report_request() + _lessons_context(lessons_path)
    else:
        # structured=False — we structure the output via a deterministic reformat call
        # (local models are weak at structured-output tool-calling).
        agent = build_simple_agent(chat, tools, structured=False)
        request = _preloaded_request(provider) + _lessons_context(lessons_path)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": request}]},
        config={"recursion_limit": 40},
    )
    text = _final_text(result)

    # Structure the free-form analysis into InsightReport (incl. memory_decisions). Local
    # models are weak at structured-output tool-calling, so use a deterministic reformat call.
    report = _structure_via_reformat(chat, text) or _coerce_report(_extract_json(text), text)

    # ── Learning loop: fold the agent's curation into the lessons memory ──
    reinforced: list[str] = []
    if lessons_path:
        from datetime import date as _date
        from .memory import apply_curation, decay, load_lessons, save_lessons
        today = _date.today().isoformat()
        decisions = [d.model_dump() if hasattr(d, "model_dump") else d for d in (report.memory_decisions or [])]
        # normalize MemoryDecision → apply_curation's expected shape
        existing_ids = {l.id for l in load_lessons(lessons_path)}
        norm = []
        for d in decisions:
            rid = d.get("reinforce")
            new_text = (d.get("new_text") or "").strip()
            ev = d.get("evidence", "")
            if rid and rid in existing_ids:
                norm.append({"reinforce": rid, "evidence": ev})
            elif new_text:
                norm.append({"new": {"text": new_text, "category": d.get("category", "other")}, "evidence": ev})
            elif ev:
                # model referenced a non-existent lesson with no new_text — salvage the
                # observation as a new lesson from its evidence rather than dropping it.
                norm.append({"new": {"text": ev, "category": d.get("category", "other")}, "evidence": ev})
        lessons = load_lessons(lessons_path)
        lessons, reinforced = apply_curation(lessons, norm, today)
        lessons = decay(lessons, today, stale_days=stale_days)
        save_lessons(lessons_path, lessons)

    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name(),
        "model": model,
        "report": report.model_dump(),
        "reinforced_lessons": reinforced,
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log.info(f"Insight written → {out_path} (confidence {report.confidence}; "
             f"{len(reinforced)} lessons reinforced)")
    return record


def _final_text(result) -> str:
    """Extract the last assistant text from a deepagents/LangGraph result."""
    msgs = result.get("messages") if isinstance(result, dict) else None
    if not msgs:
        return str(result)
    last = msgs[-1]
    content = getattr(last, "content", None)
    if content is None and isinstance(last, dict):
        content = last.get("content")
    if isinstance(content, list):  # content blocks
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def read_insights(path: str = "options_insights.jsonl") -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        pass
    return out
