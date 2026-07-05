# Finance Specialist Subgraph — Spec

> **Feature slug:** finance-specialist
> Siblings: [`plan.md`](./plan.md) (files/steps/ADRs/edge-cases) · [`tasks.md`](./tasks.md) (granular units + Loop AC)

## Behavior / What

Deliver the **finance domain specialist** — the second demo domain, deliberately built
to **prove the specialist scaffold is reusable** with no new LangGraph wiring. It
answers spend questions over a CSV transaction ledger via the **ledger connector**:
`date,account,category,amount,currency` rows parsed into typed entries, published as
typed MCP tools (`ledger.categories`, `ledger.query`) with fail-closed entitlements,
and grounded through the federation fabric with the **currency travelling as
provenance units** — the generic analog of ADR-023's normalization concern (mixed
currencies in one aggregate are rejected, never silently summed).

### Observable behaviors

1. **Connector** — `mira.connectors.ledger` parses the CSV; bad header, ragged rows,
   and non-numeric amounts raise `LedgerParseError`.
2. **Denominated aggregation** — `LedgerDocument.total(category, period)` returns
   `(total, currency, count)`; mixed-currency matches raise (ADR-023's concern).
3. **Typed MCP surface** — `export_tools()` publishes `ledger.categories` /
   `ledger.query` as ADR-031 contracts (`connector:ledger:*` entitlements, read-only).
4. **Grounded federation** — `fabric.federation.query()` returns an attributed result;
   `Provenance.units` carries the currency.
5. **Specialist reuse** — `build_finance_specialist()` wraps `FINANCE_DOMAIN`
   (`domain_id="finance"`, prefix `ledger.`) via the same `build_specialist_subgraph`;
   state is isolated from the research domain on the same thread id, and `ledger.*`
   tools are invisible to other domains (scaffold allow-listing, fail-closed).

## Acceptance Criteria

- [x] Ledger connector parses typed entries and rejects malformed CSV
- [x] Category/period totals are denominated; mixed currencies rejected
- [x] `ledger.*` tools export as typed, read-only, entitlement-bearing contracts
- [x] Federation query returns an attributed answer with currency-as-units provenance
- [x] `REPRESENTATIVE_FINANCE_QUERY` runs end-to-end through the specialist
- [x] No new LangGraph wiring — second instantiation of the shared scaffold
- [x] Import isolation lint and full offline test suite pass
