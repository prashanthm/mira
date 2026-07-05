# Research Specialist Subgraph — Tasks

> **Feature slug:** research-specialist · Spec: [`spec.md`](./spec.md) · Plan: [`plan.md`](./plan.md)

Ordered implementation units. All shipped with the initial extraction.

---

## Task 1 — Docs connector

Markdown corpus parser + `SourceConnector` adapter + typed `docs.*` tool specs.

### Files
- Create `src/mira/connectors/docs.py`, `tests/fixtures/handbook.md`, `tests/test_docs_connector.py`

## Loop AC

- [x] AC-1: parse extracts front-matter + sections; malformed input raises
  - verify: `pytest tests/test_docs_connector.py -q`
- [x] AC-2: `docs.*` contracts are read-only with `connector:docs:*` entitlements
  - verify: `pytest tests/test_docs_connector.py::test_connector_publishes_typed_read_only_mcp_tools -q`

---

## Task 2 — Research specialist

`RESEARCH_DOMAIN` + `build_research_specialist()` with the per-domain query-inference hook.

### Files
- Create `src/mira/orchestration/specialists/research.py`, `tests/test_research_specialist.py`
- Modify `specialists/domains.py`, `specialists/__init__.py`, `orchestration/__init__.py`

## Loop AC

- [x] AC-1: representative handbook query returns the middleware section with provenance
  - verify: `pytest tests/test_research_specialist.py -q`
- [x] AC-2: import isolation lint passes
  - verify: `python3 tools/lint_imports.py src/mira`
