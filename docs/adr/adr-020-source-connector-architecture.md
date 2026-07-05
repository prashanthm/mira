# ADR-020: Source Connector Architecture

## Status

Accepted

## Context

Enterprise source data lives in heterogeneous systems — document corpora, transaction
ledgers, transactional warehouses, event streams, time-series historians — often before
or instead of a unified lake. The accepted federation strategy
([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md)) decided the **logical access rule**
(query-in-place by default; every source is one optional connector) and states it governs the fabric and
the connectors. This ADR decides the **connector architecture**: how each source is connected so
**no source is privileged** and the platform works **with or without** any given enterprise data
platform (an initiative success criterion). It conforms to the platform's MCP tool surface
(inherited mcp-server ADR-001, FastMCP), typed tool contracts
([ADR-031](./adr-031-typed-tool-contracts.md)), and provider isolation
([ADR-002](./adr-002-provider-abstraction-pattern.md)).
Physical storage of any aggregated copies is [ADR-021](./adr-021-storage-engine-selection.md), not here.

## Decision Drivers

1. **Every source is one source among many** — research headline + ADR-019; the plain-source success criterion.
2. **Query-in-place (ADR-019)** — connectors implement the accepted federation rule.
3. **Source-quirk + vendor-SDK isolation (ADR-002)** — source specifics must not leak into business logic.
4. **Governed surface** — sources exposed as MCP tools with typed contracts (ADR-031), carrying provenance and units/reference-frame metadata.
5. **Scales across 5+ source types** — add a source by adding an adapter.

## Research & Rubric

Scored per-source adapters behind MCP vs consolidate-into-one-platform-first vs direct
point-to-point against no-privileged-source, works-with-or-without-any-platform,
query-in-place conformance, source-quirk isolation, MCP/typed-contract governance,
provenance metadata, and scalability. Adapters-behind-MCP wins — it is the
anti-corruption/adapter pattern, implements ADR-019, and is the research's validated shape.
Self-contained on the adapter/federation pattern plus accepted ADR-019; internal ADRs fix
the surface and storage split.

## Decision

Implement **per-source connector adapters behind the MCP tool surface**, conforming to the ADR-019
query-in-place strategy.

**1. Adapter per source type**
- One **adapter per source type** — each an anti-corruption layer that translates source specifics
  into a uniform internal shape (`SourceConnector` → `SourceRecord` + `Provenance`,
  `src/mira/connectors/base.py`). Two demo adapters ship in-tree: **`docs`** (Markdown document
  corpus, research domain — provenance carries section anchors) and **`ledger`** (CSV transaction
  ledger, finance domain — provenance carries the currency as its unit). Hypothetical `warehouse`,
  `stream`, and `timeseries` adapters follow the same shape. **No adapter is the foundation.**
- Vendor SDKs / source clients live **only in `providers/`**
  ([ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md)/[ADR-002](./adr-002-provider-abstraction-pattern.md));
  business logic and the agent never import them. The demo adapters are dependency-free by design.
- A module-level **registry** resolves a connector factory by source type, so a new source is added
  by registering a new adapter rather than touching business logic.

**2. Exposed as governed MCP tools**
- Each adapter exposes its capabilities as **MCP tools with typed contracts**
  ([ADR-031](./adr-031-typed-tool-contracts.md)) — `docs.search`/`docs.sections` for the docs
  connector, `ledger.query`/`ledger.categories` for the ledger connector — agents reach sources
  only through the MCP surface (inherited mcp-server ADR-001), not direct SDK calls. Entitlements
  are **fail-closed**: a tool with no explicit grant is not callable.
- Tools carry **provenance + units/reference-frame metadata** (inherited mcp-server ADR-021,
  LLM-context metadata in responses) for the semantic spine to reconcile.

**3. Access strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))**
- **Query-in-place by default** (operational/immovable/system-of-record sources — ledgers, document
  corpora, historians, streams); selective aggregation for analytics/RAG is ADR-019's rule, with
  physical storage in [ADR-021](./adr-021-storage-engine-selection.md).
- Provenance is preserved; source data is treated as **untrusted** (guardrails
  [ADR-037](./adr-037-bidirectional-guardrail-pipeline.md)) and **grounded** with attribution
  ([ADR-040](./adr-040-decision-trace-audit.md)).

**4. Phasing**
- Phase 1 ships the **federation skeleton + the first connectors** (ADR-019 roadmap); further
  adapters are added incrementally — each a feature under the connectors epic.

**Rejected alternatives:**

- **Consolidate-first (ingest everything into one enterprise platform, connect to it only)** — Rejected:
  refuted by the research (no single platform covers enrichment/lineage for the cross-source role;
  forced consolidation impractical) and violates "works with or without any given platform."
- **Direct point-to-point integrations (agent calls each source SDK)** — Rejected: leaks source
  quirks + vendor SDKs into business logic (ADR-002), bypasses the governed MCP surface, doesn't scale.
- **One generic connector for all sources** — Rejected: sources differ too much (a Markdown corpus
  vs a transaction ledger vs a historian stream vs a relational warehouse); a per-source adapter is
  the right boundary.

## Consequences

### Becomes Easier

- No source is privileged; the platform works with or without any enterprise data platform; new sources = new adapters registered by source type.
- Source quirks + vendor SDKs are isolated; agents see a uniform, governed MCP tool surface.
- Provenance and units/reference-frame metadata travel with the data for the semantic spine and grounding — section anchors for docs, currency units for ledger entries.
- Implements the accepted federation strategy directly.

### Becomes Harder

- Each adapter carries real per-source complexity (binary formats, stream semantics, relational schemas) — ongoing build.
- The declare-provenance / reconcile-in-spine split must stay clean across many adapters.
- Per-source auth must map onto the inherited secrets/identity model without a new scheme.

## Applies To

- `src/mira/connectors/` — source connectors, MCP export, registry (primary)
- `src/mira/fabric/` — federation engine the connectors feed
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — the access strategy connectors implement
- [ADR-031](./adr-031-typed-tool-contracts.md) — typed MCP contracts the connectors expose; [ADR-021](./adr-021-storage-engine-selection.md) — storage for aggregated copies
- [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)/[ADR-023](./adr-023-unit-of-measure-normalization.md)/[ADR-024](./adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md) — semantic spine reconciles connector metadata; [ADR-026](./adr-026-catalog-service-design.md)/[ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) — catalog
- Inherited: mcp-server ADR-001 (FastMCP tool surface), mcp-server ADR-021 (units/reference-frame metadata in responses)

## Links

- ADR file: `docs/adr/adr-020-source-connector-architecture.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-020
