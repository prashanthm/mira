# ADR-026: Catalog Service Design

## Status

Accepted

## Context

The catalog's problem statement is **"metadata, lineage, and grounding spine"** — without it, the
platform cannot answer "what data exists, where did it come from, and can I trust it" across
federated and selectively-aggregated sources. This ADR is explicitly scoped **distinct from the
knowledge-graph store**: [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) (drafted in
this same wave) owns the **semantic knowledge-graph** — the domain ontology and entity relationships
that unify federated and aggregated sources. This ADR owns the **catalog** — the
metadata/provenance/lineage/schema/quality records that inventory *what data exists* and *where it
came from*, which the knowledge graph consumes as its substrate rather than re-implements.

The catalog must fit the storage-role seam [ADR-021](./adr-021-storage-engine-selection.md) already
committed to: four logical roles (knowledge-graph store, vector index, state/cache, relational)
behind [ADR-002](./adr-002-provider-abstraction-pattern.md) Protocols, with the knowledge-graph role's
engine defaults deliberately deferred until ADR-027 names the graph model ("model-first, not
engine-first"). It must also normalize metadata across every
[ADR-020](./adr-020-source-connector-architecture.md) connector adapter — the `docs` and `ledger`
demo connectors and future `warehouse`/`stream`/`timeseries` adapters alike — consistent with the
[ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) federation rule that
lineage/provenance apply whether data is federated in place or selectively aggregated.

## Decision Drivers

1. **The catalog problem statement** — "metadata, lineage, and grounding spine," explicitly distinct
   from the knowledge-graph store.
2. **ADR-021 storage-role seam** — the relational role is reserved for structured metadata; the
   knowledge-graph role is reserved for ADR-027's not-yet-decided semantic model (model-first
   sequencing).
3. **ADR-019/ADR-020 federation + connector rules** — provenance and lineage must apply uniformly
   across federated and selectively-aggregated data, and across every source adapter, with none
   privileged.
4. **Grounding requirement** — agent answers must trace to a source record (the eval framework,
   [ADR-045](./adr-045-eval-framework-ci-safety-gate.md), asserts claim→source linkage via decision
   traces); the catalog is the join key that traceability needs.
5. **Source-agnostic scope** — the catalog must normalize metadata from schema-rich sources (a
   warehouse's typed columns, an enterprise platform's versioned record kinds) as well as
   lightly-structured ones (a Markdown corpus's front-matter, a CSV ledger's header), without
   privileging any.

## Research & Rubric

Scored a dedicated catalog service distinct from the knowledge-graph spine vs folding
metadata/provenance/lineage into the knowledge graph vs adopting an existing OSS catalog product
(DataHub/OpenMetadata-class) wholesale against fit to the industry-consensus catalog/KG boundary,
fit to the ADR-021 storage-role seam, standards-backed metadata shape, right-sizing to the epic's
scope, source-agnostic connector coverage, operational simplicity/portability, and grounding
traceability. The dedicated-catalog option wins — it matches every production catalog's convergent
architecture (entity + pluggable aspect model), keeps the ADR-021 model-first sequencing intact,
and is standards-backed (W3C PROV for provenance, OpenLineage for lineage) without importing a full
third-party platform's scope. Self-contained on DataHub/OpenMetadata/Amundsen architecture
practice, W3C PROV, the OpenLineage spec, and data-quality/contract tooling; internal ADRs fix the
storage role and the knowledge-graph hand-off.

## Decision

Build a **dedicated catalog service, architecturally distinct from the knowledge-graph spine**, using
an **entity + pluggable-aspect metadata model** — the pattern every dominant production catalog
(DataHub, OpenMetadata, Amundsen) converges on independent of vendor.

**1. What the catalog tracks (four record kinds, each a first-class aspect on a dataset/source entity)**

- **Dataset/source records** — one per connector-visible dataset (a Markdown corpus, a ledger CSV,
  a warehouse table, a stream topic), carrying its
  [ADR-020](./adr-020-source-connector-architecture.md) adapter/source identity (which connector,
  which source system) so every dataset the fabric can see is inventoried regardless of whether it
  is federated or aggregated.
- **Provenance** — shaped on the **W3C PROV** model (Entity / Activity / Agent, with
  `wasGeneratedBy` / `wasDerivedFrom` / `wasAttributedTo` relations): which connector, transform, or
  aggregation job produced or touched a record, and who/what is accountable for it.
- **Lineage** — shaped on the **OpenLineage** model (Job / Run / Dataset entities with extensible
  facets): run-level events for aggregation pipelines
  ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) Rule 2), so a
  selectively-aggregated copy always traces back to its federated origin.
- **Schema/quality metadata** — per-dataset schema (the docs connector's front-matter and section
  structure; the ledger connector's `date,account,category,amount,currency` header contract;
  compatible with a source's own versioned schema model where the source has one) plus
  data-quality check results (schema validation, freshness, row-count, custom expectations) as a
  pluggable aspect, not a separate system.

**2. Where it sits**

- The catalog runs behind the **relational storage role**
  [ADR-021](./adr-021-storage-engine-selection.md) already committed to — no new storage-role
  class, no engine commitment beyond that role's per-profile defaults.
- It is reached only through [ADR-002](./adr-002-provider-abstraction-pattern.md) Protocols,
  consistent with every other fabric component.

**3. Relationship to the knowledge-graph spine ([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md))**

- **The catalog inventories what data exists and where it came from. The knowledge graph models how
  domain entities relate.** The knowledge graph **consumes** catalog records (dataset identity,
  provenance, lineage) as its substrate for grounding, and adds semantic entity relationships
  (canonical typed identities per [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md),
  cross-source entity links) on top — it does not re-implement dataset bookkeeping, and the catalog
  does not model domain semantics.
- The exact catalog-to-KG hand-off contract (which catalog fields the graph model consumes) is
  ADR-027's to define; this ADR fixes the boundary, not the consumption API.

**4. Source-agnostic normalization**

- One internal metadata model normalizes provenance/lineage/schema across every
  [ADR-020](./adr-020-source-connector-architecture.md) adapter — so a schema-rich enterprise
  platform's metadata is one input to the catalog, not a privileged or required one, exactly as a
  bare CSV's is.

**Rejected alternatives:**

- **Fold metadata/provenance/lineage directly into the knowledge-graph spine (no separate catalog)** —
  Rejected: contradicts the epic's own framing ("distinct from the knowledge-graph store"), contradicts
  the industry-consensus catalog/KG boundary the current literature draws explicitly, and violates the
  model-first sequencing ADR-021 already committed to for the knowledge-graph storage role
  ("finalize KG-store engine defaults after ADR-027 names the graph model").
- **Adopt an existing OSS catalog product wholesale (e.g. deploy DataHub or OpenMetadata as-is)** —
  Rejected: right architectural shape, wrong altitude — ships browsing UI, glossary, and access-request
  workflows the problem statement does not ask for; adds a new infra class every deployment
  profile (including on-prem,
  [ADR-047](./adr-047-deployment-profiles-and-packaging.md)/[ADR-048](./adr-048-secure-cloud-runtime-and-network-isolation.md))
  would have to run; and its source-connector framework is warehouse-centric rather than built for
  the fabric's heterogeneous adapters (document corpora, ledgers, streams, historians). The
  **metadata model** (entity + aspect) these products popularized is adopted; the **product** is not.

## Consequences

### Becomes Easier

- Every dataset the fabric can see — federated or aggregated, from any connector — is inventoried in
  one place with consistent provenance and lineage, regardless of source adapter.
- Agent answers can be traced to a source record via the catalog's provenance/lineage records — the
  join key the eval framework's claim→source linkage assertion (ADR-045) needs.
- The catalog and the knowledge-graph spine (ADR-027) can be designed and built independently once the
  boundary is fixed — the catalog does not block on ADR-027's graph-model decision, and vice versa.
- No new storage-role class or engine commitment — the catalog reuses the ADR-021 relational role.
- Standards-backed shape (W3C PROV, OpenLineage) gives a known vocabulary instead of an ad hoc schema.

### Becomes Harder

- A second metadata-bearing component (catalog) alongside the knowledge graph means the boundary
  between "what exists" and "how it relates" must be actively maintained as both evolve — a fuzzy
  boundary would re-create the duplication this ADR rejected.
- The catalog-to-KG hand-off contract is not fixed here (deferred to ADR-027); until that lands, the
  knowledge-graph spine cannot fully specify its own substrate consumption.
- Per-adapter provenance/lineage instrumentation is ongoing work across every ADR-020 connector —
  the catalog model is only as good as what each adapter reports.
- Schema-rich sources' native metadata shapes are sourced from their published docs but not yet
  verified against live instances in this decision's research — those source-facing aspects need
  empirical confirmation during connector implementation.

## Applies To

- Catalog & grounding — this decision's primary home.
- `src/mira/fabric/` — federation engine the catalog inventories.
- `src/mira/connectors/` — source adapters the catalog normalizes metadata from.
- [ADR-021](./adr-021-storage-engine-selection.md) — relational storage role the catalog runs behind.
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — federation rule the catalog
  tracks lineage/provenance for.
- [ADR-020](./adr-020-source-connector-architecture.md) — connector adapters the catalog normalizes
  across.
- [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) — knowledge-graph spine that
  consumes catalog records as its substrate.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — claim→source linkage the catalog's
  provenance records support.

## Links

- ADR file: `docs/adr/adr-026-catalog-service-design.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-026
