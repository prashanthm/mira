"""Run the panel and persist a structured InsightReport."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from .llm import OllamaUnavailable, build_model
from .panel import build_insight_panel, report_request
from .providers.base import DataProvider
from .schema import InsightReport
from .tools import make_tools

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


def run_panel(provider: DataProvider, model: str = "qwen2.5:7b",
              base_url: str = "http://localhost:11434",
              out_path: str = "options_insights.jsonl",
              subagent_settings: dict | None = None) -> dict:
    """Generate one insight from `provider`'s data via the local panel; append to out_path.

    Returns the recorded record. Raises OllamaUnavailable if the local LLM is down.
    """
    chat = build_model(model=model, base_url=base_url)  # raises OllamaUnavailable if down
    tools = make_tools(provider)
    agent = build_insight_panel(chat, tools, subagent_model_settings=subagent_settings)

    result = agent.invoke({"messages": [{"role": "user", "content": report_request()}]})
    # deepagents returns a LangGraph state; the final assistant message holds the text.
    text = _final_text(result)
    report = _coerce_report(_extract_json(text), text)

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
