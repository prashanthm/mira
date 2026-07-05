# Finance Specialist Subgraph — Tasks

> **Feature slug:** finance-specialist · Spec: [`spec.md`](./spec.md) · Plan: [`plan.md`](./plan.md)

Ordered implementation units. All shipped with the initial extraction.

---

## Task 1 — Ledger connector

CSV parser + `SourceConnector` adapter + typed `ledger.*` tool specs with
currency-as-provenance-units.

### Files
- Create `src/mira/connectors/ledger.py`, `tests/fixtures/ledger.csv`, `tests/test_ledger_connector.py`

## Loop AC

- [x] AC-1: parse/totals behave; malformed CSV and mixed currencies raise
  - verify: `pytest tests/test_ledger_connector.py -q`
- [x] AC-2: `ledger.*` contracts are read-only with `connector:ledger:*` entitlements
  - verify: `pytest tests/test_ledger_connector.py::test_connector_publishes_typed_read_only_mcp_tools -q`

---

## Task 2 — Finance specialist (scaffold reuse proof)

`FINANCE_DOMAIN` + `build_finance_specialist()` — second instantiation of the shared
scaffold, no new graph wiring.

### Files
- Create `src/mira/orchestration/specialists/finance.py`, `tests/test_finance_specialist.py`
- Modify `specialists/domains.py`, `specialists/__init__.py`, `orchestration/__init__.py`

## Loop AC

- [x] AC-1: representative spend query returns a denominated, attributed answer
  - verify: `pytest tests/test_finance_specialist.py -q`
- [x] AC-2: ledger tools invisible to other domains; state isolated across domains
  - verify: `pytest tests/test_specialist_scaffold.py tests/test_finance_specialist.py -q`
- [x] AC-3: import isolation lint passes
  - verify: `python3 tools/lint_imports.py src/mira`
