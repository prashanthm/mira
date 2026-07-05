# `mira` package layers

Import isolation enforced by `tools/lint_imports.py` (ADR-001, ADR-007):

| Layer | Path | Cloud SDKs | langchain / langgraph |
|-------|------|------------|------------------------|
| Providers | `providers/` | Allowed | Forbidden |
| Orchestration | `orchestration/` | Forbidden | Allowed |
| Core / other | `core/` and siblings | Forbidden | Forbidden |

Run `make lint-imports` before pushing.
