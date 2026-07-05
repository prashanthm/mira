# ADR-021: Storage Engine Selection

## Status

Accepted

## Context

The accepted federation strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))
aggregates **selectively** (embeddings/RAG corpus, session/eval artifacts) while most data stays
federated at source — and explicitly **defers physical storage to this ADR**, stating the engines
(Neptune/OpenSearch/DynamoDB/Redis/RDS) are **"illustrative only."** This ADR decides the storage for
the data the fabric keeps local indexes for, **without** coupling the architecture to specific cloud
engines, given provider-agnostic multi-placement ([ADR-047](./adr-047-deployment-profiles-and-packaging.md),
incl. on-prem/Outposts) and the [ADR-002](./adr-002-provider-abstraction-pattern.md) storage Protocols.

## Decision Drivers

1. **ADR-019 "engines illustrative only"** — decide roles + abstraction, not specific engines.
2. **Polyglot data shapes** — graph, vector, KV/cache, relational need different stores.
3. **Provider-agnostic / on-prem portability (ADR-047)** — no hard cloud-engine lock-in.
4. **ADR-002 seams** — stores sit behind Protocols (swappable, testable).
5. **Data residency / integrity (NIST, regulated)** — residency must be a profile concern.

## Research & Rubric

`Research & rubric — ADR-021`. Scored role-based polyglot persistence behind the Protocols vs hard-committing specific cloud engines vs a single multi-model store against right-store-per-shape, respecting ADR-019's "illustrative only", on-prem portability, swappability, ops simplicity, and scale. The role-based, abstraction-first option wins — it commits to the roles + seams while leaving engines as per-profile defaults. Self-contained on polyglot-persistence + data-store-abstraction practice + NIST; internal ADRs fix what's stored and the seams.

## Decision

Adopt **role-based polyglot persistence behind the [ADR-002](./adr-002-provider-abstraction-pattern.md)
Protocols.** Commit to the **storage roles and the abstraction**; treat the **concrete engine as a
per-profile default, not an architectural commitment** (per [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md)).

**Four logical storage roles** (for the selectively-aggregated data only — [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md)):

| Role | Holds | Behind | Default direction (per profile; not a commitment) |
|------|-------|--------|---------------------------------------------------|
| **Knowledge-graph store** | KG nodes/edges (semantic spine; model = [ADR-027](./adr-list.md)) | role Protocol | managed graph DB (cloud) / portable graph or PG-based (on-prem) |
| **Vector index** | embeddings / RAG corpus | role Protocol | OpenSearch / dedicated vector DB (cloud) · **pgvector** (small/on-prem) |
| **State / cache** | session + durable KV (memory tiers, [ADR-017](./adr-017-memory-architecture.md)) | [`IStateStore`](./adr-002-provider-abstraction-pattern.md) | managed KV/Redis (cloud) / Redis or SQLite (on-prem) |
| **Relational** | session/eval artifacts, structured metadata | role Protocol / [`IObjectStore`](./adr-002-provider-abstraction-pattern.md) for blobs | RDS/Postgres |

- **Engine = config, not architecture.** Each role is reached through a Protocol; the engine is a
  `providers/`-level choice ([ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md)/[ADR-002](./adr-002-provider-abstraction-pattern.md)),
  selectable per deployment profile, swappable without touching business logic ([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment).
- **Portability:** every role has a **portable on-prem default** (e.g. Postgres + pgvector) so no
  profile depends on a specific cloud service; residency is a profile concern ([ADR-048](./adr-048-secure-cloud-runtime-and-network-isolation.md)).
- **Scope:** governs only the **selectively-aggregated** data; source-platform records and operational/immovable
  sources stay **federated** ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md)), not stored here.

**Rejected alternatives:**

- **Hard-commit to specific cloud engines (Neptune + OpenSearch + DynamoDB + Redis + RDS)** —
  Rejected: contradicts ADR-019 ("illustrative only"), couples the architecture to one cloud (fails
  on-prem/Outposts portability), and bakes engine choice into the decision record.
- **Single multi-model store for everything** — Rejected as the architecture: compromises graph/vector
  performance at scale and couples all roles to one engine. Allowed as a **profile default**
  (e.g. Postgres + pgvector) for small/on-prem deployments.
- **No abstraction (use engine SDKs directly)** — Rejected: leaks the engine upward, breaks
  swappability/testability and ADR-002 isolation.

## Consequences

### Becomes Easier

- Each data shape gets a fit store; engines swap per profile without touching business logic.
- On-prem/Outposts portability preserved (portable defaults); residency is a profile knob.
- Honors ADR-019 — engines stay defaults, not architectural commitments.
- Mock the Protocols for tests; no engine in unit tests.

### Becomes Harder

- Polyglot persistence = more systems to run than a single store (mitigated by per-profile defaults).
- A per-profile default matrix must be maintained (cloud vs on-prem engine choices).
- The KG-store-here vs graph-model-in-ADR-027 split must stay clean; finalize KG-store engine defaults **after** ADR-027 names the graph model (model-first, not engine-first).

## Applies To

- **MIRA-FABRIC** — storage for aggregated data (primary)
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — what is aggregated vs federated
- [ADR-002](./adr-002-provider-abstraction-pattern.md) — `IStateStore`/`IObjectStore` + role Protocols
- [ADR-047](./adr-047-deployment-profiles-and-packaging.md) / [ADR-048](./adr-048-secure-cloud-runtime-and-network-isolation.md) — per-profile engine defaults + residency
- [ADR-017](./adr-017-memory-architecture.md) (memory uses state/cache) / [ADR-027](./adr-list.md) (KG model on the KG store) / [ADR-028](./adr-list.md)/[ADR-030](./adr-list.md) (retrieval uses the vector index)

## Links

- ADR file: `docs/adr/adr-021-storage-engine-selection.md`
- Research & rubric: `research/adr-021-storage-engine-selection.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-021
- Epic: MIRA-FABRIC
