# Mira

**M**ulti-agent **I**nsight & **R**easoning **A**rchitecture — a reusable, product-agnostic agentic-AI framework. A [deepagents](https://pypi.org/project/deepagents/) sub-agent research panel runs over a **local LLM (Ollama)**, reads data through a pluggable **DataProvider**, and emits a structured, **advisory** `InsightReport`.

Mira knows nothing about any specific product. A product plugs in via a config + a resource→source mapping. The first application is **Sentinel** (the trading agent): Mira evaluates its options recommendations, A–D grades, scorecard, and the agent's actual trades, and writes qualitative insights back for the learning loop.

## Design

- **Local-only LLM** — Ollama at `localhost:11434`. No cloud, no data leaves the machine. If Ollama is down, runs no-op cleanly.
- **Sub-agent panel** — an orchestrator delegates to `options-analyst` + `actions-analyst`, then synthesizes one report.
- **Provider seam** — `DataProvider.read(resource)`; `JsonlProvider` backs it with files today; a backend store can swap in later with zero agent changes.
- **Advisory only** — insights inform; they never auto-change a playbook or touch any execution path.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
ollama serve            # if not already running; pull a model: ollama pull qwen2.5:7b

# generate an insight for the Sentinel application
.venv/bin/mira insights --config configs/sentinel.yaml
# or list local models
.venv/bin/mira models
```

## Layout

| Path | Role |
|------|------|
| `mira/llm.py` | local Ollama model builder + health check |
| `mira/providers/` | the `DataProvider` seam (`JsonlProvider`) |
| `mira/tools.py` | provider-backed tools the agent calls |
| `mira/panel.py` | the deepagents sub-agent research panel |
| `mira/insight.py` | run the panel → structured `InsightReport` → JSONL |
| `mira/schema.py` | the `InsightReport` contract |
| `mira/cli.py` | `mira insights` / `mira models` |
| `configs/sentinel.yaml` | the Sentinel application (paths + model + output) |
| `scripts/install-launchd.sh` | Mira's own nightly 17:40 ET job |

## Adding another product

Write a new `configs/<product>.yaml` mapping the resource keys to that product's data. No framework code changes.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q     # providers, schema, and insight parsing — no Ollama needed
```
