# Research Specialist Subgraph — Plan

> **Feature slug:** research-specialist · Sibling spec: [`spec.md`](./spec.md) · Tasks: [`tasks.md`](./tasks.md)

## Depends On

| Dependency | Status | Notes |
|------------|--------|-------|
| ADR-013 Reasoning Pattern & Loop-Safety Bounds | Accepted | `ReasoningLoop` in `src/mira/orchestration/reasoning.py` |
| ADR-014 Domain-Agent & Supervisor Routing | Accepted | Specialist-as-subgraph topology |
| ADR-020 Source Connector Architecture | Accepted | `SourceConnector` protocol + registry in `src/mira/connectors/base.py` |
| ADR-031 Typed Tool Contracts | Accepted | `ToolContract` + `export_tools` |
| Specialist scaffold | Implemented | `build_specialist_subgraph`, `DomainSpec`, `SpecialistResult` in `specialist_scaffold.py` |

## Files

### Create

| Path | Purpose |
|------|---------|
| `src/mira/connectors/docs.py` | Markdown corpus connector: `parse_markdown`, `DocsConnector`, typed `docs.*` tool specs |
| `src/mira/orchestration/specialists/research.py` | `REPRESENTATIVE_RESEARCH_QUERY`, `_infer_docs_search` hook, `build_research_specialist()` |
| `tests/fixtures/handbook.md` | Demo corpus (front-matter + three sections) |
| `tests/test_docs_connector.py` | Parse, protocol conformance, MCP export, federation grounding |
| `tests/test_research_specialist.py` | Representative query E2E + supervisor contract |

### Modify

| Path | Change |
|------|--------|
| `src/mira/orchestration/specialists/domains.py` | Declare `RESEARCH_DOMAIN` (`docs.` prefix) |
| `src/mira/orchestration/specialists/__init__.py`, `orchestration/__init__.py` | Re-exports |

## Edge cases

- Unterminated front-matter, section-less documents → `DocsParseError`.
- Search term matching no section → `DocsParseError` (never a silent empty answer).
- Query-inference hook falls through to the scaffold's structured noop on
  non-representative actions; explicit `act:tool:docs.search:{...}` channel always works.
