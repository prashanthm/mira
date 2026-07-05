# Mira

**M**ulti-agent **I**nsight & **R**easoning **A**rchitecture — a reference agentic-AI
implementation: multi-agent orchestration, a source-agnostic data fabric, and governed
tool access behind one warm service. Domain-agnostic by construction: a new use case
plugs in as a *domain* (a connector + typed tool contracts + a specialist subgraph),
never by touching the core.

The runtime is one **warm service** (long-lived process, health endpoints, streaming
turns with a visible plan) that runs **fully offline with no cloud account and no API
keys** via the `local` echo provider. The LLM is a *URL*: point `LLM_BASE_URL` at any
OpenAI-compatible endpoint (Ollama, vLLM, a LiteLLM proxy in front of Bedrock) without
changing code or profile.

## Try it

```bash
make setup     # local venv + editable install
make start     # warm service on 127.0.0.1:8080 (offline echo model)
make smoke     # health + one streamed turn
make test      # offline pytest suite
make lint      # import-boundary lint + sanitize-check
```

```bash
python -m mira                      # same as `make start`
python -m mira --port 9000          # bind a different port
python -m mira --check              # boot the app and exit 0 (no socket) — a fast smoke test
python -m mira --profile standalone # pick a deployment profile (default: kubernetes)
```

Run one agent turn in-process:

```python
from mira.providers.local import build_local_bundle
from mira.app import build_app

app = build_app("kubernetes", bundle=build_local_bundle())
print(app.run_turn("what does the handbook say about middleware ordering?")["response"])
for event in app.stream_events("show the plan"):
    print(event.kind)
```

## Chat CLI (`mira-chat`)

An interactive LLM + MCP-tools chatbot. Needs an MCP server, a tool-capable local
model (e.g. Ollama `qwen2.5`), and the extras: `pip install -e ".[llm,mcp]"`.

```bash
mira-chat                                            # zero-config local defaults
mira-chat --mcp http://host:8765/mcp --token "$JWT"  # MCP server needing a bearer token
mira-chat --model qwen2.5:32b                        # pin a model
mira-chat --llm-url http://my-vllm:8000/v1           # any OpenAI-compatible LLM
```

## What's inside (`src/mira/`)

| Package | Responsibility |
|---|---|
| `app.py`, `__main__.py` | composition root + `python -m mira` entrypoint |
| `chat.py` | the `mira-chat` one-step chatbot CLI (LLM + MCP tools) |
| `core/` | warm service (health/drain), typed streaming events + SSE, attribution, middleware pipeline, layered memory, resilience |
| `orchestration/` | LangGraph runtime, ReAct reasoning loop with budget bounds, the specialist scaffold, MCP tool discovery — the only layer that may import langchain/langgraph |
| `model/` | provider-agnostic gateway, fallback chain + circuit breaker, cost/quota routing, eval-gated versioning registry |
| `providers/` | vendor-SDK boundary — `local` (offline echo), `openai_compatible` (any `/v1`), `aws` — the only layer that may import cloud SDKs |
| `fabric/` | data fabric — federate-vs-aggregate policy, query-in-place federation, storage roles, provenance |
| `connectors/` | source connectors + MCP export + server registry; demo domains: `docs` (Markdown corpus), `ledger` (CSV transactions) |
| `tools/` | typed tool contracts (flat JSON-schema, fail-closed entitlements), invocation, authz |
| `config/` | deployment profiles + validation |

Import boundaries are CI-enforced (`tools/lint_imports.py`): langchain/langgraph only
in `orchestration/`, cloud SDKs only in `providers/`.

## Extending to a new use case

A domain is three small pieces, demonstrated twice in-tree (`research` over the docs
connector, `finance` over the ledger connector):

1. a **connector** implementing `SourceConnector` (see `connectors/docs.py`),
2. **typed MCP tool contracts** published via `export_tools` (fail-closed entitlements),
3. a **specialist** — a `DomainSpec` + `build_specialist_subgraph(...)` (~25 lines,
   see `orchestration/specialists/finance.py`).

The walkthrough lives in [`docs/extension-guide.md`](docs/extension-guide.md).
Architecture decisions are recorded in [`docs/adr/`](docs/adr/adr-list.md).

## Deploy assets

`Dockerfile` plus `deploy/{helm,terraform,fargate}` are reference-only — functional
but not wired to any pipeline. The same image is intended to run locally and on
Kubernetes/ECS; placement is env/Helm-driven, never baked in (ADR-047).

## Status

Private reference implementation. The prior Mira (deepagents/Ollama insight panel
consumed by Sentinel) is preserved on the `legacy/v0` branch; its nightly launchd job
is disabled until the Sentinel use case is re-ported as a domain on this runtime.
