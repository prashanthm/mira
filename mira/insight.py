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


def run_panel(provider: DataProvider, model: str = "qwen2.5:7b",
              base_url: str = "http://localhost:11434",
              out_path: str = "options_insights.jsonl",
              subagent_settings: dict | None = None,
              mode: str = "simple") -> dict:
    """Generate one insight from `provider`'s data via the local agent; append to out_path.

    mode="simple" (default): one deep agent with the compact data pre-loaded — fast and
    reliable on local hardware. mode="panel": the full sub-agent research panel (opt-in;
    deeper but much slower on small local models).

    Returns the recorded record. Raises OllamaUnavailable if the local LLM is down.
    """
    chat = build_model(model=model, base_url=base_url)  # raises OllamaUnavailable if down
    tools = make_tools(provider)

    if mode == "panel":
        agent = build_insight_panel(chat, tools, subagent_model_settings=subagent_settings)
        request = report_request()
    else:
        # structured=False — we structure the output via a deterministic reformat call
        # (local models are weak at structured-output tool-calling).
        agent = build_simple_agent(chat, tools, structured=False)
        request = _preloaded_request(provider)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": request}]},
        config={"recursion_limit": 40},
    )
    text = _final_text(result)

    # Structure the free-form analysis into InsightReport. Local models reliably emit
    # the analysis as prose but are weak at structured-output tool-calling, so we use a
    # deterministic reformat call (a simple text→JSON conversion they handle well), then
    # fall back to text extraction if even that is imperfect.
    report = _structure_via_reformat(chat, text) or _coerce_report(_extract_json(text), text)

    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name(),
        "model": model,
        "report": report.model_dump(),
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log.info(f"Insight written → {out_path} (confidence {report.confidence})")
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
