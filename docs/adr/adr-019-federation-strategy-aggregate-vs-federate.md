# ADR-019: Federation Strategy — Aggregate vs Federate

## Status

Accepted

## Context

Enterprise source data lives in **heterogeneous systems** — transactional warehouses, live event streams, transaction ledgers, document stores, time-series historians — often **before or instead of** a unified lake. The initiative success criterion requires documenting the **aggregate-vs-federate rule as an ADR** and proving a **grounded query against a plain source** (one with no platform-managed copy) through the fabric.

Research validated:

- **Query-in-place / virtualization** for operational and immovable data.
- **Hybrid lakehouse + federation** for analytics/RAG — not either/or.
- **Any enterprise data platform is one source**, not a mandatory consolidation point; the "unify everything in one canonical store first" framing was refuted.

Physical storage engine selection (graph store, search index, cache, relational) is **ADR-021** (Tier 2). This ADR records the **logical data-access strategy** — what stays at source vs what may be copied — governing the fabric (`src/mira/fabric/`) and the connectors (`src/mira/connectors/`).

## Decision Drivers

1. **Initiative charter** — "Federation defaults to query-in-place … selectively aggregates into a lakehouse for analytical/RAG workloads."
2. **Success criterion** — "Federation decision rule documented as an ADR."
3. **Research verdict table** — copying operational, large-binary, or system-of-record data into a lake before query is impractical; permissions and data gravity differ by source.
4. **No privileged consolidation point** — grounded answers must not require first loading every source into any single canonical store; that would contradict the source-agnostic thesis.
5. **Phase roadmap** — Phase 1 federation **skeleton** + first connectors; full RAG aggregation Phase 3.

## Decision

Adopt a **hybrid federation model** as the default data-access strategy for the data fabric.

**Rule 1 — Federate in place (default):**

Query data **at the source** via connectors behind MCP when any of:

- Data is **operational / near-real-time** (live event streams, time-series historians).
- Data is a **system of record or bound to its host system** (transaction ledgers, document corpora with their own lifecycle and authoring workflow, warehouse tables owned by another team).
- **Legal or contractual** constraints prohibit copying (customer data residency, license-bound stores).
- **Freshness** requirement exceeds practical sync latency to a lake.

**Rule 2 — Selective aggregation (explicit opt-in per workload):**

Copy or index into platform-managed stores **only when**:

- Workload is **analytical or RAG** (embeddings, hybrid retrieval, eval goldens).
- **Repeated cross-source joins** at query time are cost-prohibitive (profile documented in workload spec).
- **Aggregation job** is registered in catalog with lineage, retention, and entitlements ([ADR-026](./adr-026-catalog-service-design.md), Phase 2+).

**Rule 3 — Every source is one connector:**

Even a source that positions itself as an enterprise-wide platform attaches behind MCP like any other ([ADR-020](./adr-020-source-connector-architecture.md)). The semantic spine (ADR-022–ADR-025) reconciles identity, units, and reference frames **above** sources — no source is the prerequisite consolidation layer.

**Rule 4 — Semantic catalog unifies both paths:**

Metadata, lineage, and cross-source entity links live in the **knowledge-graph catalog spine** ([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md), Phase 2) whether data is federated or aggregated.

**Phase 1 scope:**

- Implement rule enforcement in the **connector + fabric skeleton** — a single decision point (`src/mira/fabric/policy.py`) classifies every `(source type, data kind)` pair, so the routing decision is documented per query plan rather than scattered.
- Ship **file-native demo connectors** as the Phase 1 proof paths — the `docs` Markdown-corpus connector (research domain) and the `ledger` CSV-transaction connector (finance domain) — lower operational risk than live stream taps.
- Defer lakehouse aggregation pipelines to Phase 3 unless a Phase 1 feature spec explicitly requires a minimal index (e.g. eval fixtures in object storage).

The implemented classification (`src/mira/fabric/policy.py`):

| Class | Pattern | Identifier (source type / data kind) |
|----------|---------|-----------------|
| Transactional warehouse | Federate | `warehouse` |
| Live event stream | Federate | `stream` |
| Transaction ledger (finance demo) | Federate | `ledger` — CSV ledger connector |
| Document corpus (research demo) | Federate | `docs` — Markdown docs connector |
| Time-series historian | Federate | `timeseries` |
| Embeddings / RAG corpus | Aggregate | `embeddings`, `rag`, `rag-corpus` (stores per ADR-021) |
| Session / eval artifacts | Aggregate | `session`, `eval`, `eval-goldens` (stores per ADR-021) |
| Anything unrecognized | Federate | conservative default — data stays at source, entitlements stay at their existing boundary |

**Rejected alternatives:**

- **Lake-first / consolidate-then-serve** — Rejected: impractical for immovable and system-of-record sources; refuted unify-then-virtualize framing; violates the plain-source proof path.
- **Federation-only (no aggregation ever)** — Rejected: RAG, memory tiers, and eval CI require local indexes; research validates hybrid.
- **A mandatory canonical system of record** — Rejected: contradicts the initiative's source-agnostic core thesis; no single platform covers enrichment, workflows, and lineage well enough to be forced into the cross-source role.
- **RAG/KG as sole correctness mechanism** — Rejected: grounding is necessary but not sufficient — this drives the HITL/XAI ADRs, it does not eliminate the federation decision.

## Consequences

### Becomes Easier

- Customers without a pre-consolidated data platform receive grounded answers — core differentiator.
- Permission boundaries stay at source systems where entitlements already exist.
- Phase 1 scope is bounded (skeleton + demo connectors) without building a lakehouse first.

### Becomes Harder

- Query planning must route per-source with different latency and failure modes.
- Cross-source joins at query time are expensive — the semantic spine and catalog become load-bearing (Phase 2).
- Operations must monitor **both** connector health and aggregation pipeline health in Phase 3.

## Applies To

- `src/mira/fabric/` — federation engine; `policy.py` is this ADR's single decision point
- `src/mira/connectors/` — source adapters ([ADR-020](./adr-020-source-connector-architecture.md))
- Catalog and semantic spine — unification layer, Phase 2 ([ADR-026](./adr-026-catalog-service-design.md), [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md), ADR-022–ADR-025)
- RAG / graph-retrieval workloads — aggregation consumers, Phase 3 (ADR-028–ADR-030)
- [ADR-021](./adr-021-storage-engine-selection.md) — physical storage engines (Tier 2)

## Links

- ADR file: `docs/adr/adr-019-federation-strategy-aggregate-vs-federate.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-019
