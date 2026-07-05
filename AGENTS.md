# AGENTS.md

Guidance for coding agents (and humans) working in `mira`. This file documents what is
actually true of this repo today, not aspirations.

## What this repo is

Mira — a reference agentic-AI implementation: multi-agent orchestration, a
source-agnostic data fabric, and governed tool access behind one warm WSGI service.
Python ≥ 3.12, src-layout package `mira`. Core deps are deliberately light: `langgraph`,
`langchain-core`, `jsonschema`; everything heavier is an optional extra (`[llm]`,
`[mcp]`, `[dev]`). No FastAPI — the HTTP surface is hand-rolled WSGI + SSE.

Planning artifacts live **in this repo** under `docs/` (ADR catalog in `docs/adr/`,
architecture in `docs/architecture/`, the extension walkthrough in
`docs/extension-guide.md`). Check `docs/adr/adr-list.md` before proposing new
architecture — decisions are numbered ADR-001…ADR-048 and code docstrings cite them
by number.

## Code layout (`src/mira/`)

| Package | Responsibility | Boundary rule |
|---|---|---|
| `app.py`, `__main__.py` | composition root + `python -m mira` entrypoint | framework-free |
| `chat.py` | `mira-chat` CLI (LLM + MCP tools) | framework-free |
| `core/` | warm service, streaming + SSE, attribution, middleware, memory, resilience | framework-free |
| `orchestration/` | LangGraph runtime, reasoning loop, specialist scaffold, MCP tools | **only** place langchain/langgraph may be imported |
| `model/` | gateway, fallback, routing, versioning, cost spans | framework-free |
| `providers/` | vendor-SDK boundary (local echo / openai_compatible / aws) | **only** place cloud SDKs may be imported |
| `fabric/` | federate-vs-aggregate policy, federation, storage roles, provenance | framework-free |
| `retrieval/` | hybrid dense+sparse retrieval, RRF fusion, corrective RAG loop | framework-free |
| `semantic/` | entity resolution, knowledge graph, catalog, conflicts, fusion | framework-free |
| `connectors/` | connector framework + MCP export; demo domains `docs` + `ledger` | framework-free |
| `tools/` | typed tool contracts, invocation, authz | framework-free |
| `config/` | deployment profiles | framework-free |

The boundaries are mechanically enforced: `make lint-imports` fails the build on a
langchain/langgraph import outside `orchestration/` or a cloud-SDK import outside
`providers/` (`tools/lint_imports.py`, tested by `tests/test_lint_imports.py`).

`make sanitize-check` (part of `make lint`, run in CI) greps for upstream-extraction
strings that must never reappear; `tools/sanitize_extract.py` is the provenance record
of the original extraction.

## Conventions

- **12-factor env config.** Two orthogonal axes, never a single local/cloud branch:
  infra `PLATFORM` (`local`|`aws`) selects the provider bundle; `LLM_BASE_URL` selects
  the model independently. Profiles (`DEPLOYMENT_PROFILE`) are named default-sets.
- **Specs convention:** engineering detail for a feature lives in
  `specs/<feature>/{spec,plan,tasks}.md` (see `specs/research-specialist/` and
  `specs/finance-specialist/` for worked examples).
- **Tests:** offline-only, no network or credentials, near-1:1 with source modules,
  flat under `tests/`. New modules ship with a matching test file.
- **Adding a domain** is registration, not core surgery: connector (`SourceConnector`)
  → typed tool contracts (`export_tools`, fail-closed entitlements) → specialist
  (`DomainSpec` + `build_specialist_subgraph`). See `docs/extension-guide.md`.
- **Branching:** trunk-based, short-lived branches named `<type>/<slug>`
  (e.g. `feat/supervisor-routing`), PRs into `main`.

## Build / test / run

```bash
make setup          # venv + editable install (prefers uv)
make start          # warm service on 127.0.0.1:8080, offline echo model
make smoke          # health + one streamed turn (needs `make start` running)
make test           # pytest -q
make lint           # lint-imports + sanitize-check
python -m mira --check   # boot-and-exit smoke (no socket)
```

CI (`.github/workflows/ci.yml`) runs `make lint` and `make test` on Python 3.12.

## Current-state caveats (true today)

- `deploy/` assets (Helm/Terraform/Fargate) are functional references but **not wired
  to any pipeline** — no image push, no `terraform apply`, no CD.
- No typecheck in CI; `ruff` is configured but not gated.
- Phases B-E are built: supervisor routing + agent cards (`orchestration/`), the
  offline evals harness (`evals/`, CI-gated), retrieval/RAG (`retrieval/`), the
  semantic spine (`semantic/`), guardrail detectors + escalation + decision traces +
  `/explain` (`core/`), and AgentOps (`model/cost_attribution.py`, `config/slos.py`,
  `core/incidents.py`). Remaining: ADR-015/016 (Phase F) and the Sentinel re-port (G).
- `legacy/v0` branch holds the previous Mira (deepagents/Ollama insight panel used by
  Sentinel); its launchd job is disabled pending re-port as a domain here.
- LICENSE is all-rights-reserved pending an IP review before any open-sourcing.
