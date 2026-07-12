"""Measurement harness for the analyze-cost-efficiency goal (E0 method).

Builds the real composition (live Vantage MCP + DeepSeek tier routes), wraps
the OpenAI client's ``chat.completions.create`` to record API-reported usage
(the only view that sees deepseek-reasoner's hidden reasoning tokens), runs
the fixed 5-symbol panel SEQUENTIALLY with refresh=1 (per-run attribution =
recorder delta around each analyze; graph-internal threads all hit the same
recorder), and prints one summary line per symbol plus the panel median.

Run from the repo root with the DeepSeek env set:
    .venv/bin/python claudedocs/goals/analyze-cost-efficiency/bench.py
"""
from __future__ import annotations

import json
import statistics
import threading
import time

PANEL = ("PLTR", "ACN", "MSFT", "O", "SOXL")
QUESTION = "what should I do about {sym}?"


class UsageRecorder:
    """Wraps chat.completions.create; accumulates API-reported usage."""

    def __init__(self, completions):
        self._orig = completions.create
        self._lock = threading.Lock()
        self.prompt = 0
        self.completion = 0
        self.calls = 0

    def snapshot(self) -> tuple[int, int, int]:
        with self._lock:
            return self.prompt, self.completion, self.calls

    def create(self, *args, **kwargs):
        result = self._orig(*args, **kwargs)
        usage = getattr(result, "usage", None)
        with self._lock:
            self.prompt += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.completion += int(getattr(usage, "completion_tokens", 0) or 0)
            self.calls += 1
        return result


def main() -> None:
    from mira.__main__ import _default_registry
    from mira.app import build_app

    app = build_app(registry=_default_registry())
    backend = app.bundle.llm
    client = backend._ensure_client()  # bench-only: instrument the transport
    recorder = UsageRecorder(client.chat.completions)
    client.chat.completions.create = recorder.create

    provider = app.service._analyze_provider

    rows = []
    for sym in PANEL:
        p0, c0, n0 = recorder.snapshot()
        t0 = time.monotonic()
        out = provider(sym, QUESTION.format(sym=sym), True)
        elapsed = time.monotonic() - t0
        p1, c1, n1 = recorder.snapshot()
        empty = [r["domain"] for r in (out or {}).get("results", [])
                 if sorted((r.get("answer") or {}).keys()) == ["raw"]]
        row = {
            "symbol": sym,
            "total_tokens": (p1 - p0) + (c1 - c0),
            "prompt_tokens": p1 - p0,
            "completion_tokens": c1 - c0,
            "llm_calls": n1 - n0,
            "seconds": round(elapsed, 1),
            "empty_domains": empty,
            "synthesis_chars": len((out or {}).get("synthesis") or ""),
        }
        rows.append(row)
        print(json.dumps(row), flush=True)

    totals = [r["total_tokens"] for r in rows]
    print(json.dumps({
        "median_total_tokens": statistics.median(totals),
        "mean_total_tokens": round(statistics.mean(totals), 1),
        "panel": list(PANEL),
    }))


if __name__ == "__main__":
    main()
