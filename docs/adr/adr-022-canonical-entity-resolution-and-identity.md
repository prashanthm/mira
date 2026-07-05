# ADR-022: Canonical Entity Resolution & Identity

## Status

Accepted

## Context

The accepted federation strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))
queries source data **at the source** by default — document corpora, transaction ledgers,
warehouses, streams, historians — and explicitly names every source as **one connector, not a
consolidation point**: the semantic spine reconciles identity, units, and reference frames
**above** sources. The accepted storage decision
([ADR-021](./adr-021-storage-engine-selection.md)) already reserves a
**knowledge-graph store role** for this spine, without yet naming its graph model (that is
[ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md), Phase 2).

The problem this leaves open: real-world entities are **structured, not flat** — a counterparty
holds one or more accounts, a document contains one or more sections, a customer places one or more
orders — and the **same real-world entity is referenced differently by different sources**: a
ledger row's account string, a registry identifier (tax ID, LEI-style legal-entity code, customer
number), an operator-local display name embedded in a document header, an export file's internal
identifier. Without a named resolution component, every domain agent or tool call that spans more
than one source must reinvent its own join logic, with no structural guarantee it respects
parent≠child distinctions (an account is not its counterparty; a section is not its document) and
no persisted record of what was matched to what.

The initiative's success criteria require canonical entity resolution to exist "as a **named
component**, not a black box" and to be verified end-to-end on real data. This ADR decides **how**
the fabric resolves canonical identity — the match strategy and where the result lives — not the
concrete graph ontology (ADR-027) or the per-domain key formats (implementation detail).

## Decision Drivers

1. **ADR-019's "every source is one connector" constraint** — the resolution approach must not
   require funneling every source through any single platform's ID space to count as resolved;
   that would contradict the initiative's source-agnostic differentiator.
2. **ADR-021's reserved knowledge-graph store role** — a storage role for the semantic spine
   already exists in the accepted architecture; the resolution approach should use it, not
   introduce a parallel store.
3. **Parent ≠ child is a standards-grade distinction, not a modeling nicety** — registries and
   master-data practice consistently model containment explicitly (a legal entity *holds*
   accounts; a document *contains* sections; a customer *places* orders). The resolution approach
   must preserve this structurally, not rely on every caller getting the join right.
4. **Established systems already treat identifiers as aliases** — mature master-data platforms
   keep a typed alias/crosswalk set (an official registry key is one alias among several inputs,
   not a sole primary key); the fabric's approach should be consistent with, not duplicate, this.
5. **Not every source carries a reliable shared key** — free-text document headers, ad hoc export
   names, and operator-local naming have no registry key at ingestion time; a resolution approach
   that only handles the has-a-key case is incomplete.
6. **Auditability and reversibility (regulated settings)** — match decisions must be inspectable
   and correctable, not silently auto-merged; this rules out destructive, non-reviewable merging.

## Research & Rubric

Scored (1) a deterministic-key-first crosswalk with an explicit canonical-identity graph node and a
bounded probabilistic fallback, (2) one-platform-as-canonical-registrar, (3) pure probabilistic/ML
matching for all sources, and (4) no canonical layer (ad hoc per-query resolution) against fit to
ADR-019's every-source-is-one-connector constraint, structural preservation of parent≠child
relationships, coverage of sources with no reliable shared key, auditability/reversibility, fit to
the ADR-021 reserved knowledge-graph store role, and operational cost. Option 1 wins — it is the
only option that respects ADR-019, structurally enforces parent≠child via distinct canonical node
types, covers both keyed and unkeyed sources, and produces auditable, non-destructive matches that
fit directly into the storage role ADR-021 already reserved.

## Decision

Adopt a **deterministic-key-first canonical entity resolution model**, materialized as canonical
identity nodes in the knowledge-graph store role ([ADR-021](./adr-021-storage-engine-selection.md)),
with a bounded probabilistic fallback for sources that carry no reliable shared key.

**1. Typed canonical nodes per entity type, not one undifferentiated node.**
Every resolved entity becomes a canonical node of a specific type — e.g. `Counterparty` and
`Account` in the finance demo, `Document` and `Section` in the research demo, `Customer`/`Order` in
a commerce domain — never a single generic "entity" node — with explicit containment edges for the
1:N relationships (`Account --belongsTo--> Counterparty`, `Section --partOf--> Document`).
Source-agnostic: this structure is populated the same way whichever connector supplies the record.

**2. Deterministic tier: registry-key match, first.**
When a source record carries a stable shared identifier — an account number, a canonical document
path plus section anchor, a legal-entity registry code, a customer number (per-domain key schemes
vary — the exact key mapping is a feature-spec concern, not fixed here) — that key is the primary
deterministic match signal. A matching key resolves the source record to an existing canonical
node, or creates one if none exists.

**3. Crosswalk representation: canonical node + typed cross-reference edges, never a destructive
merge.**
Each source-system record keeps its own record identity; a typed `xref`/`resolvedTo` edge links it
to the canonical node. Where a source system maintains its own alias set, that alias set is
consumed as **one input alias source among several** feeding this edge set — not elevated to the
fabric's canonical registrar (per ADR-019, every source is one connector). No source record's
fields are overwritten by the resolution process; provenance is fully preserved and traceable per
source.

**4. Probabilistic fallback tier for unkeyed sources.**
When no reliable shared key exists (free-text document headers, ad hoc export names, operator-local
naming), a bounded probabilistic match — field-agreement scoring in the Fellegi-Sunter tradition
(name similarity, address/location, dates, categorical attributes) — proposes a candidate canonical
node. Matches above a high-confidence threshold may auto-link; matches in an uncertain band are
staged for human review rather than auto-merged (concrete thresholds and review-queue ownership are
a semantic-spine feature-spec concern, not fixed here). Auto-linking below any confidence bound is
explicitly disallowed.

**5. Scope boundary with ADR-027.**
This ADR decides the **resolution model** (deterministic-first, graph-crosswalk representation,
probabilistic fallback, typed parent≠child canonical nodes) and that it lives in the ADR-021
knowledge-graph store role. It does **not** decide the concrete graph ontology, property schema, or
query language for that store — that is
[ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) (Knowledge-Graph Semantic Catalog
Spine), matching the ADR-021 precedent of separating storage role from graph model.

**6. Worked proof cases.**
The demo domains are the named proof cases: the `ledger` connector's account/counterparty
identities (finance) and the `docs` connector's document/section identities (research). The same
canonical-node-plus-xref pattern is expected to generalize to other entity types (customers,
vendors, facilities, projects) as domains are onboarded, but that generalization is left to future
feature specs, not pre-built here.

**Rejected alternatives:**

- **One-platform-as-canonical-registrar** — Rejected: requires funneling every source through a
  single platform's ID space to count as resolved, directly contradicting ADR-019's "every source
  is one connector, not a consolidation point" and the initiative's source-agnostic differentiator.
- **Pure probabilistic/ML matching for all sources** — Rejected: discards the reliable
  deterministic signal that exists for the majority of records (an account number, a registry
  code, a canonical path), defaulting every match — including the easy ones — into an
  auto-merge-above-threshold pattern that master-data-management practice flags as risky without
  governance; higher ongoing cost for no accuracy benefit where a key already exists.
- **No canonical layer (ad hoc per-query resolution)** — Rejected: fails the initiative's own
  success criterion that entity resolution exist "as a named component, not a black box"; pushes
  unbounded, uncoordinated join logic into every domain agent, with no structural guarantee the
  parent≠child distinctions are respected and no persisted record of any match decision to audit
  or correct.

## Consequences

### Becomes Easier

- Domain agents and tools query **one canonical identity** per entity regardless of which
  source(s) hold the underlying data — no per-caller reimplementation of cross-source joins.
- Parent≠child structure is enforced structurally (distinct node types + containment edges), not
  left to convention.
- Adding a new source only requires feeding its keys/aliases into the existing crosswalk — no
  rework of any other source's resolution, and no requirement to map into another platform's ID
  space first.
- Match decisions are auditable and reversible: source records are never overwritten, and every
  crosswalk edge is inspectable.

### Becomes Harder

- Sources with no reliable key (free-text headers, ad hoc exports, operator-local names) require
  the probabilistic fallback tier and a review workflow for uncertain matches — this is real
  ongoing operational surface, not a one-time build.
- Per-domain key variance (account-numbering schemes, registry-code formats, document-path
  conventions) means the deterministic tier cannot hardcode a single key format;
  domain-specific key mapping must be maintained as new domains are onboarded.
- The knowledge-graph store now carries a load-bearing, cross-initiative dependency: this ADR's
  resolution model must stay compatible with whatever graph ontology ADR-027 ultimately selects —
  the two ADRs must be read together, not independently.

## Applies To

- Semantic spine — this decision's primary home; features derive from it once ratified.
- `src/mira/fabric/` — federation engine that queries across resolved canonical identities.
- `src/mira/connectors/` — source adapters (`docs`, `ledger`, and future `warehouse`/`stream`/`timeseries`) that feed keys/aliases into the crosswalk.
- Catalog ([ADR-026](./adr-026-catalog-service-design.md)) — metadata/lineage catalog that references canonical identities.
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — federation strategy this resolution model operates above.
- [ADR-020](./adr-020-source-connector-architecture.md) — connector architecture supplying source records to the crosswalk.
- [ADR-021](./adr-021-storage-engine-selection.md) — knowledge-graph store role this resolution model is materialized in.
- [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) — owns the concrete graph ontology/property model for the canonical nodes and xref edges this ADR requires.
- [ADR-023](./adr-023-unit-of-measure-normalization.md) / [ADR-024](./adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md) — sibling semantic-spine decisions operating on the same canonical entities this ADR resolves.

## Links

- ADR file: `docs/adr/adr-022-canonical-entity-resolution-and-identity.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-022
