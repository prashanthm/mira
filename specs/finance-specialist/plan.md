# Finance Specialist Subgraph — Plan

> **Feature slug:** finance-specialist · Sibling spec: [`spec.md`](./spec.md) · Tasks: [`tasks.md`](./tasks.md)

## Depends On

| Dependency | Status | Notes |
|------------|--------|-------|
| ADR-013 / ADR-014 / ADR-020 / ADR-031 | Accepted | Same foundations as research-specialist |
| ADR-019 Federation Strategy | Accepted | Query-in-place grounding through the fabric |
| ADR-023 Normalization (genericized) | Accepted | Currency as the demo normalization concern |
| `research-specialist` (first domain) | Implemented | Proves the scaffold once; this proves reuse |

## Files

### Create

| Path | Purpose |
|------|---------|
| `src/mira/connectors/ledger.py` | CSV ledger connector: `parse_ledger`, `LedgerConnector`, typed `ledger.*` tool specs |
| `src/mira/orchestration/specialists/finance.py` | `REPRESENTATIVE_FINANCE_QUERY`, `_infer_ledger_query` hook, `build_finance_specialist()` |
| `tests/fixtures/ledger.csv` | Demo ledger (two months, three categories, USD) |
| `tests/test_ledger_connector.py` | Parse, totals, mixed-currency rejection, MCP export, federation grounding |
| `tests/test_finance_specialist.py` | Representative query E2E, supervisor contract, cross-domain invisibility |

### Modify

| Path | Change |
|------|--------|
| `src/mira/orchestration/specialists/domains.py` | Declare `FINANCE_DOMAIN` (`ledger.` prefix) |
| `src/mira/orchestration/specialists/__init__.py`, `orchestration/__init__.py` | Re-exports |

## Edge cases

- Mixed currencies within one aggregate → `LedgerParseError` (normalize first; ADR-023).
- Empty period/category match → error, never a silent zero.
- `ledger.*` tools filtered out for non-finance domains (fail-closed allow-listing).
