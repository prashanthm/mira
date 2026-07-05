# ADR-027: Knowledge-Graph Semantic Catalog Spine

## Status

Accepted

## Context

The accepted federation strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))
routes most source data to **query-in-place** connectors (document corpora, ledgers, warehouses,
streams, historians) and explicitly assigns Rule 4 to this ADR: "metadata, lineage, and
cross-source entity links live in the **knowledge-graph catalog spine** (ADR-027, Phase 2) whether
data is federated or aggregated."
The accepted storage decision ([ADR-021](./adr-021-storage-engine-selection.md)) already reserves a
**knowledge-graph store role** behind an [ADR-002](./adr-002-provider-abstraction-pattern.md)
Protocol for exactly this spine, deliberately deferring "the concrete graph model" to this ADR and
noting engine defaults for that role should finalize **after** this ADR names the model
("model-first, not engine-first").

[ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) (same wave) has already gone one
layer deeper than ADR-021 and committed to **how entities are represented** in that store role:
typed canonical nodes per entity type — e.g. `Counterparty`/`Account` in the finance demo,
`Document`/`Section` in the research demo — linked by explicit containment edges, with each
source-system record kept intact and connected via a typed `xref`/`resolvedTo` crosswalk edge
rather than a destructive merge. ADR-022 explicitly leaves **the concrete graph ontology, property
schema, or query language** to this ADR.

A sibling decision in this same wave, [ADR-026](./adr-026-catalog-service-design.md) (Catalog
Service Design), owns the **metadata/provenance/lineage catalog** as a component distinct from the
knowledge-graph store — ADR-021 itself frames these as separate concerns. This ADR does not decide
catalog service architecture, provenance capture, or lineage tracking; it decides only the **graph
model and ontology** the knowledge-graph store role uses to represent canonical entities and their
relationships, which the catalog (ADR-026) and the semantic-spine features both depend on.
Retrieval strategy over this graph — hybrid search (ADR-028), agentic RAG (ADR-029), and
graph-plus-vector fusion / GraphRAG (ADR-030) — is explicitly out of scope here and deferred to
Phase 3; this ADR must not foreclose those later decisions, only avoid deciding them prematurely.

## Decision Drivers

1. **ADR-019 Rule 4** — the spine must unify metadata, lineage, and cross-source entity links
   "whether data is federated or aggregated," and must not require any single platform as the
   consolidation point (Rule 3: "every source is one connector").
2. **ADR-021's reserved, model-deferred store role** — a knowledge-graph store role and Protocol
   seam already exist; this ADR names the model that role holds, not a new store.
3. **ADR-022's already-committed node/edge shape** — typed canonical nodes plus containment edges
   plus `xref`/`resolvedTo` crosswalk edges to source records must be representable directly in
   whatever ontology this ADR selects; re-deriving that shape here would contradict ADR-022.
4. **Regulated-industry auditability** — the initiative's audit-trail requirements (ADR-022's
   match-decision auditability, the transformation audit trail of ADR-024) favor a graph model
   with a standard, machine-checkable constraint and provenance layer over one with none.
5. **Existing domain ontology prior art** — most domains this platform targets already have a
   published ontology or structural taxonomy (finance has an industry-maintained financial-business
   ontology; documents and data catalogs have schema.org, DCAT, and PROV-O; many sectors publish a
   consortium taxonomy). Reusing rather than re-deriving whatever exists in the target domain
   lowers cost and risk.
6. **Engine-neutrality (ADR-021 "illustrative only")** — the model choice should not force a
   single-vendor engine commitment; the illustrative cloud default and portable equivalents
   support the same model on-prem.
7. **Do not foreclose Phase 3 GraphRAG** — the model must not block the graph-plus-vector fusion
   direction ADR-030 will decide later, even though this ADR does not design that fusion.

## Research & Rubric

Scored (1) RDF/OWL with the ontology seeded from an existing published domain ontology and
extended/corroborated with a second, independently published taxonomy, (2) a labeled property
graph with a custom schema built from scratch, (3) RDF/OWL built entirely from scratch, and (4) a
hybrid property-graph store with an OWL reference schema mapped in at write time — against fit to
ADR-019's unification/no-privileged-source rule, fit to ADR-022's already-committed canonical
node/edge shape, formal governance (SHACL/OWL constraints and reasoning) for a regulated setting,
reuse-vs-build cost, engine flexibility under ADR-021, traversal performance, and compatibility
with Phase 3 GraphRAG. Option 1 wins — it is the only option that gets governance-grade constraint
checking, the lowest build cost via a maintained existing ontology, and the parent≠child
structural fit ADR-022 already requires, without over-committing to a single engine.

## Decision

Adopt **RDF/OWL as the graph model** for the ADR-021 knowledge-graph store role, with the ontology
**seeded from an existing domain ontology where one exists** and **corroborated against a second,
independently published taxonomy** so no single source system's schema alone shapes the spine.

**1. Graph model: RDF/OWL, not a labeled property graph, for the semantic spine.**
Entities and relationships in the knowledge-graph store role are represented as RDF triples with an
OWL class/property hierarchy, validated with SHACL shapes. This gives the spine a standard,
machine-checkable constraint layer and a standard reasoning layer — neither of which a labeled
property graph provides natively — which the initiative's audit-trail and regulated-setting
requirements (ADR-022, ADR-024) call for.

**2. Ontology seed: an existing published domain ontology, not built from scratch.**
Each domain's ontology starts from whatever published prior art that domain has — for the finance
demo, an industry-maintained financial-business ontology already defines counterparty, account,
and instrument classes; for the research/documents demo, schema.org's `CreativeWork` hierarchy,
DCAT, and PROV-O already cover documents, sections, and derivation. A seed is adopted as a
**starting point**, not copied verbatim — class/property names may be re-namespaced or extended as
the spine's own ontology (exact IRI a feature-spec concern) to avoid a hard dependency on the
upstream project's release cadence. Where a domain genuinely has no published ontology, the
domain's ontology is modeled fresh — but that is the fallback, not the default.

**3. Ontology corroboration: a second, independent taxonomy, to stay source-agnostic.**
Because [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) Rule 3 requires every
source be "one connector, not the consolidation point," the seed ontology's core classes are
cross-checked against a second, independently published standard where one exists (e.g. a sector
consortium's structural taxonomy alongside a vendor-ecosystem-derived ontology), so the spine's
core classes are corroborated by a standard outside any single source ecosystem, not defined by
one source's schema alone. This mirrors the same parent≠child structural distinctions ADR-022
already requires.

**4. Direct mapping to ADR-022's canonical node/edge shape.**
The typed canonical entity classes (e.g. `Counterparty`/`Account`, `Document`/`Section`) are OWL
classes, related by OWL object properties equivalent to ADR-022's containment edges (`belongsTo`,
`partOf`). Each source-system record becomes its own RDF resource, connected to its canonical
resource via an object property equivalent to ADR-022's `xref`/`resolvedTo` edge — never merged or
overwritten, preserving per-source provenance exactly as ADR-022 specifies.

**5. SHACL for structural validation; OWL reasoning depth kept conservative at first.**
SHACL node shapes enforce the parent≠child structural rules (an `Account` is not its
`Counterparty`; a `Section` is not its `Document`) and required properties on write.
Full OWL reasoning-profile depth (e.g. OWL 2 EL vs full DL) is **not** fixed by this ADR — the
ontology starts with structural validation only, and reasoning depth is added as concrete query
patterns emerge in feature specs, avoiding premature complexity.

**6. Engine remains a per-profile default, not fixed here.**
Consistent with [ADR-021](./adr-021-storage-engine-selection.md)'s "illustrative only" principle,
this ADR does not select a specific RDF triple store. A managed cloud triple store (SPARQL) is
available as a cloud default; Apache Jena or GraphDB are available as portable on-prem defaults.
Finalizing the per-profile engine default is left to ADR-021's placement decisions, now that the
model is named.

**7. Scope boundary with ADR-026 and ADR-030.**
This ADR decides the **graph model and ontology-seeding approach** only. It does not decide
catalog-service architecture, provenance capture, or lineage tracking
([ADR-026](./adr-026-catalog-service-design.md)), and it does not decide the graph-plus-vector
fusion or GraphRAG retrieval strategy (ADR-030, Phase 3) — it is scoped narrowly so those
decisions remain open and unforeclosed.

**Rejected alternatives:**

- **Labeled property graph (LPG) with a custom schema built from scratch** — Rejected: forfeits the
  existing domain-ontology prior art for no offsetting requirement, and property graphs have no
  standard constraint/reasoning layer, leaving governance bespoke in a regulated,
  audit-trail-carrying platform.
- **RDF/OWL built entirely from scratch (no reuse of published ontologies/taxonomies)** — Rejected:
  pays the same RDF/OWL tooling and modeling cost as the selected option while discarding the
  existing ontology and taxonomy prior art that makes the selected option cheaper and lower-risk;
  strictly dominated except on the no-privileged-source axis, which the selected option already
  achieves via the independent-taxonomy corroboration.
- **Hybrid: property-graph operational store with an OWL reference schema mapped in at write time**
  — Rejected: the dual-schema translation layer is the most expensive option to build and
  synchronize, and requires effectively committing to two engine families rather than one
  queryable-either-way store, the worst fit to ADR-021's "illustrative only" principle. The
  traversal-speed benefit it chases is not a stated requirement today.

## Consequences

### Becomes Easier

- Cross-source metadata, lineage, and entity links have one governed representation regardless of
  whether the underlying data is federated (queried at source) or aggregated — directly satisfying
  ADR-019 Rule 4.
- ADR-022's typed canonical nodes and `xref`/`resolvedTo` crosswalk edges map directly onto OWL
  classes and object properties with no re-modeling.
- SHACL gives a standard, machine-checkable way to enforce the parent≠child structural rules and
  catch malformed writes before they corrupt the spine — instead of bespoke application-level checks.
- Adding a new connector's concepts (a corpus's front-matter fields, a ledger's account/category
  vocabulary, a warehouse's relational schema) is ontology extension work, not a new
  graph-modeling exercise from zero.
- The engine choice for the knowledge-graph store role (ADR-021) can now proceed model-first, per
  ADR-021's own stated sequencing.

### Becomes Harder

- RDF/SPARQL multi-hop traversal is typically slower than labeled-property-graph traversal at large
  scale — an accepted tradeoff for governance/auditability, not eliminated by this decision; if a
  future query-latency SLO cannot be met, this ADR must be revisited rather than silently worked
  around.
- The team takes on RDF/OWL/SHACL tooling and modeling discipline, which is a smaller and less
  mainstream skill pool than property-graph tooling (e.g. Cypher).
- Each domain's ontology carries an external dependency on its seed ontology's structure and
  release cadence, even though seeds are adopted as starting points and re-namespaced rather than
  used verbatim.
- Full OWL reasoning-depth and the concrete class/property mapping for entity types beyond the
  demo domains are deliberately left open, so downstream feature specs carry real design work this
  ADR does not resolve.

## Applies To

- Catalog & grounding — this decision's primary home.
- Semantic spine — canonical entity resolution
  ([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)) materializes into the graph
  model this ADR names.
- `src/mira/fabric/` — federation engine whose query plans traverse the spine for cross-source
  joins.
- `src/mira/connectors/` — source adapters whose records become RDF resources linked into the
  spine via xref edges.
- Phase 3 graph-retrieval work — will query this spine once ADR-030 decides the fusion strategy.
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — federation strategy Rule 4
  this ADR fulfills.
- [ADR-021](./adr-021-storage-engine-selection.md) — knowledge-graph store role this ADR names the
  model for.
- [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) — canonical entity resolution
  model this ontology represents structurally.
- [ADR-026](./adr-026-catalog-service-design.md) — sibling decision on the
  metadata/provenance/lineage catalog component, distinct from this graph model.
- [ADR-028](./adr-028-hybrid-retrieval.md) / [ADR-029](./adr-029-agentic-rag.md) /
  [ADR-030](./adr-030-graph-vector-fusion.md) — retrieval, agentic RAG, and graph-plus-vector
  fusion decisions (Phase 3) that will query the spine this ADR defines without being decided by
  it.

## Links

- ADR file: `docs/adr/adr-027-knowledge-graph-semantic-catalog-spine.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-027
