"""Mira CLI — `mira insights --config configs/sentinel.yaml`."""
from __future__ import annotations

import argparse
import logging
import sys

import yaml

from .insight import run_panel
from .llm import OllamaUnavailable, available_models, ollama_up
from .providers.jsonl import JsonlProvider


def _build_provider(cfg: dict) -> JsonlProvider:
    p = cfg.get("provider", {})
    kind = p.get("kind", "jsonl")
    if kind != "jsonl":
        raise ValueError(f"unsupported provider kind '{kind}'")
    return JsonlProvider(
        provider_name=cfg.get("name", "data"),
        paths=p.get("paths", {}),
        base_dir=p.get("base_dir", ""),
    )


def cmd_insights(args: argparse.Namespace) -> int:
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    llm = cfg.get("llm", {})
    base_url = llm.get("base_url", "http://localhost:11434")
    model = args.model or llm.get("model", "qwen2.5:7b")
    out_path = args.out or cfg.get("output", "options_insights.jsonl")

    if not ollama_up(base_url):
        print(f"Ollama not reachable at {base_url} — skipping (local-LLM only, no cloud).",
              file=sys.stderr)
        return 3

    mode = args.mode or cfg.get("mode", "simple")
    provider = _build_provider(cfg)
    try:
        rec = run_panel(provider, model=model, base_url=base_url, out_path=out_path,
                        subagent_settings=llm.get("subagent_settings"), mode=mode)
    except OllamaUnavailable as e:
        print(f"Ollama unavailable: {e}", file=sys.stderr)
        return 3

    rep = rec["report"]
    print(f"Insight ({rep['confidence']} confidence) via {model}:")
    print(f"  {rep['summary']}")
    if rep.get("adjustments"):
        print("  Adjustments (advisory):")
        for a in rep["adjustments"]:
            print(f"    - {a}")
    print(f"  → {out_path}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    base = args.base_url
    if not ollama_up(base):
        print(f"Ollama not reachable at {base}.", file=sys.stderr)
        return 3
    for m in available_models(base):
        print(m)
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="mira", description="Mira agentic insight framework")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser("insights", help="Run the insight panel over a configured data provider")
    p_ins.add_argument("--config", required=True, help="Path to a config YAML (e.g. configs/sentinel.yaml)")
    p_ins.add_argument("--model", default=None, help="Override the Ollama model")
    p_ins.add_argument("--out", default=None, help="Override the output JSONL path")
    p_ins.add_argument("--mode", default=None, choices=["simple", "panel"],
                       help="simple = one agent, fast/reliable (default); panel = sub-agent research panel (slower)")
    p_ins.set_defaults(func=cmd_insights)

    p_mod = sub.add_parser("models", help="List locally available Ollama models")
    p_mod.add_argument("--base-url", default="http://localhost:11434")
    p_mod.set_defaults(func=cmd_models)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
