# ADR-024: Reference-Frame Preservation & Transformation Audit Trail

## Status

Accepted

**Scope: Optional domain plugin.** The preservation + append-only-log discipline below is core
fabric doctrine; the concrete frame registry, transform tooling, and log-entry vocabulary ship as
a per-domain plugin, enabled only for domains whose data carries transformable reference frames.
(The filename retains this ADR's original coordinate-centric title; the decision is general.)

## Context

The accepted federation strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))
queries source data **at the source** by default and names every source as **one connector, not a
consolidation point**: the semantic spine reconciles identity, units, and reference frames **above**
sources. The accepted storage decision ([ADR-021](./adr-021-storage-engine-selection.md)) reserves a
knowledge-graph store role for this spine.
[ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) decides **how the fabric resolves
canonical entity identity** across sources — the entity this ADR's transformation records attach to.

The problem this leaves open: many values are **not self-interpreting — they are only meaningful
relative to a reference frame**, and moving a value between frames is a *transform*, not a
relabeling. The pattern recurs across domains:

- **Spatial data**: a coordinate pair means nothing without its coordinate reference system and
  datum, and multiple valid transformations can exist between the same two systems (see Appendix).
- **Time**: a timestamp is ambiguous without its time zone/calendar convention; converting between
  zones across DST boundaries is a lossy-if-untracked operation.
- **Accounting bases**: the "same" figure differs under cash vs accrual basis, or under different
  fiscal-calendar conventions; restating between bases is a transform with assumptions.
- **Currency conversion** (the finance demo's frame): converting an amount between currencies
  requires an explicit, dated exchange rate — which is why the `ledger` connector *refuses* to
  aggregate mixed currencies ([ADR-023](./adr-023-unit-of-measure-normalization.md)) rather than
  silently converting: a conversion is a logged transform under this ADR, never an implicit step.

Different sources declare their frames differently or not at all: a self-describing connector
carries frame metadata per response (`Provenance.crs` in Mira's connector shape, populated from an
upstream metadata envelope where one exists — inherited mcp-server ADR-021); a file header may
declare a frame in free text or omit it; a legacy extract may carry an implicit, undocumented
house convention. Frame registries themselves evolve — transformations get superseded (still
valid, a better equivalent now exists) or deprecated (determined erroneous) — so a record naming
only "source frame → target frame," with no operation identity, becomes ambiguous over time. A
fabric that silently re-expresses values in "a" canonical frame, or that records only a current
frame tag with no operation history, cannot answer the question an analyst or auditor will
eventually ask: *what frame was this value originally in, and exactly what happened to it before I
saw this number?*

This ADR decides **how** the fabric preserves source reference frames and records transformation
provenance — not the concrete graph ontology for the log records
([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md)) or per-domain frame-mapping
tables (implementation detail).

## Decision Drivers

1. **The decision question itself is a non-negotiable constraint** — the semantic spine's
   acceptance criteria require one verifiable truth across sources; silently transforming or
   discarding a source frame would make that truth unverifiable and is explicitly out of bounds.
2. **ADR-019's "every source is one connector" constraint** — frame preservation and the operation
   log must work uniformly across all sources; it cannot assume every source self-describes as
   well as the best-instrumented connector does.
3. **Carried frame metadata is surfaced per response, but transiently** — the connector/MCP layer
   emits frame context per tool call for LLM interpretation (inherited mcp-server ADR-021), but
   does not persist a dataset-level record; this ADR's audit trail must consume and persist that
   signal, not re-derive it.
4. **Real-world frame failure modes are well documented, not hypothetical** — axis-order and
   convention confusion between near-identical frames is a live hazard in the geospatial ecosystem
   (Appendix); DST/zone ambiguity is its calendrical twin; a mis-dated FX rate is its financial
   twin. A record that only stores "source frame → target frame" cannot disambiguate which
   operation actually happened.
5. **Frame registries change over time** — registries distinguish superseded from deprecated
   transformations and version their own releases; a record naming only a frame pair, with no
   operation identifier, timestamp, or accuracy, becomes ambiguous as the registry evolves.
6. **Established catalog practice preserves the native/source frame rather than forcing one
   system** — forced re-expression "can be lossy" and breaks no-copy workflows (the geospatial
   catalog ecosystem made this explicit; see Appendix); the fabric should not re-litigate this by
   normalizing away source frames at ingestion.
7. **Serializable, replayable operation-record formats already exist and need not be invented** —
   the geospatial reference implementation defines a lossless, standards-backed encoding of "exactly
   what operation sequence was applied" (Appendix); time and finance domains have equivalents
   (zone database version + rule; rate source + timestamp).
8. **ADR-021's reserved knowledge-graph store role and ADR-022's canonical entity nodes** — the
   storage role and the entities these records attach to already exist in the accepted
   architecture; this ADR should use them, not introduce a parallel store.

## Research & Rubric

Scored (1) a structured transformation log keyed to canonical entities, using registry codes plus a
serializable operation record for every transform with the source frame preserved unmodified at
ingestion, (2) normalize-at-ingestion to a single canonical frame with the original discarded, (3)
a current-frame-tag field with no operation history, and (4) no structured tracking (rely on
source-system/carried metadata alone) — against never silently losing the source frame, producing
a genuine per-dataset audit trail, correctly handling the documented case of multiple valid
operations between the same frame pair, fit to the accepted knowledge-graph store role and ADR-022
canonical entities, cross-source query/display correctness, and operational cost. Option 1 wins —
it is the only option that satisfies both halves of the decision question (preservation and audit
trail), accounts for the registry-documented reality that frame-to-frame mappings are not
single-valued and change over time, and fits directly into the storage role and canonical-entity
model the initiative has already committed to.

## Decision

Adopt **permanent preservation of each source dataset's original reference-frame declaration, plus
a structured, append-only transformation log for every frame transform performed**, keyed to the
[ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) canonical entities and
materialized in the [ADR-021](./adr-021-storage-engine-selection.md) knowledge-graph store role —
packaged as an **optional per-domain plugin** enabled for domains whose data carries transformable
frames.

**1. The source frame is captured at ingestion and never overwritten.**
Every dataset entering the fabric — regardless of connector — records its declared (or, if
genuinely undeclared, explicitly flagged **unknown/unverified**) reference frame at ingestion,
using a registry code where the source names or can be mapped to one, or a serialized frame
definition where it cannot. This value is never modified in place by any later transform — it is
the permanent record of what the source said. An **unknown/unverified frame** is a distinct,
visible state, never silently defaulted to a guessed frame merely because that frame is common
(Mira's connector layer already normalizes a missing frame to an explicit `unknown` sentinel).

**2. Every frame transform performed by the fabric is logged, not just displayed.**
Any re-expression the fabric performs — at ingestion normalization, at query time for a
cross-source join, or for display/export — produces a discrete, timestamped log entry recording:
source frame, target frame, the specific operation used (a registry operation code where one
applies, or a serializable operation record where the operation is a concatenation of steps), and
accuracy/assumption metadata where the tooling exposes it (transformation accuracy and area of
validity for spatial operations; zone-database version for time; rate source, rate timestamp, and
quote convention for currency conversion). This log is **append-only**: a later transform adds a
new entry, it never rewrites or deletes a prior one.

**3. The log attaches to canonical entities and their source records, not to a global table.**
Log entries key off the [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) canonical
nodes (or the source-record nodes crosswalked to them), living in the same knowledge-graph store
role ADR-021 already reserves for the semantic spine — consistent with how ADR-022 attaches
crosswalk/xref edges to those same nodes. This keeps "what frame history does this entity's data
carry" answerable as a graph traversal from the canonical entity, not a separate lookup.

**4. Carried frame metadata is consumed as input, not re-derived.**
For self-describing sources, the frame fields the connector/MCP layer already surfaces per
response (inherited mcp-server ADR-021; `Provenance.crs` in the connector shape) are the source of
the ingestion-time capture (Component 1) and, when an upstream system's own normalization is in
effect, a log entry (Component 2) recording that upstream transform. This ADR's contribution is
**persisting** that signal per dataset and extending the same discipline to sources that carry no
equivalent envelope — it does not re-implement any source's own normalization.

**5. Ambiguity is recorded explicitly, not resolved silently.**
Where more than one valid operation exists between a source and target frame (a documented, common
case — see Appendix for the spatial instance; competing FX rate sources and zone-rule versions are
the analogues), the log entry records which specific operation was selected and, where available,
why (accuracy, locally available correction data, or an explicit operator/config choice) — never
just the frame pair. Known convention hazards (axis order for spatial frames, DST-fold resolution
for timestamps, bid/mid/ask convention for FX) are captured as explicit properties of the recorded
operation, not left implicit.

**6. Scope boundary with ADR-027.**
This ADR decides the **preservation and audit-trail model** (permanent source capture, append-only
operation log, attachment to canonical entities, consumption of carried metadata) and that it
lives in the ADR-021 knowledge-graph store role. It does **not** decide the concrete graph
ontology, property schema, or query language for the log-entry nodes/edges — that is
[ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md), matching the ADR-021/ADR-022
precedent of separating storage role from graph model.

**Rejected alternatives:**

- **Normalize-at-ingestion (single canonical frame, original discarded)** — Rejected: directly
  contradicts the decision question's requirement to never silently transform or lose the source
  frame; once the original is discarded, no downstream correction or audit is possible even in
  principle, and it re-litigates the established catalog-ecosystem precedent of preserving the
  native/source frame rather than forcing a single system.
- **Current-frame-tag only, no operation history** — Rejected: an improvement over discarding the
  original outright, but still fails the audit-trail half of the decision question — a tag with no
  history cannot answer what happened to a value before it was observed, which matters precisely
  because multiple valid operations can exist between the same frame pair and the registry of
  "correct" operations itself changes over time.
- **No structured tracking (rely on source-system/carried metadata alone)** — Rejected: works only
  as well as the least-disciplined connector, is inconsistent between self-describing sources and
  less-structured ones (free-text headers, legacy extracts), and leaves zero record of any
  transform the fabric itself performs (e.g. query-time conversion for a cross-source join) —
  failing the initiative's own "named component, not a black box" bar already established for
  canonical entity resolution
  ([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)).

## Consequences

### Becomes Easier

- An analyst or auditor can answer "what frame was this value originally in, and what happened to
  it" as a direct graph traversal from the canonical entity node — no reverse-engineering from
  source files or tribal knowledge.
- Cross-source queries that require a common frame (a portfolio total in one reporting currency; a
  join across sources in different spatial systems) can transform at query time with confidence,
  because the operation performed is logged and reproducible rather than an untracked one-off.
- Self-describing sources' existing frame metadata is reused rather than re-derived, keeping this
  ADR's implementation additive to the inherited mechanism instead of duplicating it.
- New connectors only need to feed their declared (or explicitly-unknown) frame into the same
  ingestion-capture and operation-log pattern — no per-connector bespoke provenance design.
- Domains without transformable frames simply do not enable the plugin — no dead weight in the core.

### Becomes Harder

- Every fabric-performed frame transform — including ones a developer might consider "just a
  display conversion" — must go through logged operation tooling; this is real, ongoing
  implementation discipline, not a one-time build, and a transform that bypasses the log silently
  reintroduces the problem this ADR exists to prevent.
- Sources with genuinely undeclared or unverifiable frames (a free-text header with no frame
  field, an operator-local convention with no documentation) must be explicitly flagged
  unknown/unverified rather than defaulted — this pushes a real data-quality/triage workload onto
  ingestion that a silent-default approach would have hidden (at the cost of correctness).
- The knowledge-graph store now carries additional load-bearing content (operation-log entries
  alongside ADR-022's canonical nodes and crosswalk edges); this ADR's model must stay compatible
  with whatever graph ontology ADR-027 ultimately selects — the three ADRs (021, 022, 024) must be
  read together for the storage layer to make sense.
- Append-only logging means log volume grows over time for datasets that are frequently re-queried
  across different target frames; retention/compaction policy is not fixed by this ADR and must be
  addressed before high-frequency query-time transform logging reaches production scale.

## Applies To

- Semantic spine — this decision's home; net-new features derive from it once ratified (as an
  optional plugin per domain).
- `src/mira/fabric/` — federation engine that performs query-time frame transforms across resolved
  canonical identities and must log every such transform.
- `src/mira/connectors/` — source adapters that feed source frame declarations (or explicit
  unknown-state flags) into ingestion capture.
- Catalog ([ADR-026](./adr-026-catalog-service-design.md)) — references transformation-log entries
  alongside canonical identities.
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — federation strategy this
  preservation and audit-trail model operates above.
- [ADR-021](./adr-021-storage-engine-selection.md) — knowledge-graph store role this model is
  materialized in.
- [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) — canonical entity-resolution
  model this ADR's operation log attaches to.
- [ADR-023](./adr-023-unit-of-measure-normalization.md) — static unit conversion (dictionary
  lookup, no assumptions); this ADR owns the transforms that *do* carry assumptions.
- [ADR-025](./adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md) —
  sibling semantic-spine decision on the same canonical entities and source records this ADR
  instruments.
- [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) — owns the concrete graph
  ontology/property model for the log-entry nodes/edges this ADR requires.
- Inherited: mcp-server ADR-021 — carried frame metadata this ADR consumes and persists for
  self-describing sources.

## Appendix — Worked example: geospatial coordinate reference systems

The domain this decision was first proven in is geospatial, and it remains the sharpest worked
example of every clause above:

- **Frames**: a coordinate pair like `(31.2, -103.7)` is meaningless without its coordinate
  reference system (e.g. EPSG:4326 vs a projected UTM zone) and datum (WGS84 vs NAD27 vs a
  local/regional datum); vertical values additionally need a datum reference point (mean sea
  level vs a site-local reference).
- **Registry evolution**: the EPSG dataset — the industry registry of coordinate systems and
  transformations — structurally distinguishes **superseded** operations (still valid, a better
  equivalent exists) from **deprecated** ones (determined erroneous), and versions its own release
  history. A log entry naming only "EPSG code → EPSG code" is ambiguous as the registry evolves.
- **Multiple valid operations**: the reference implementation (PROJ) can return **multiple valid
  coordinate operations** between the same pair of systems, differing in accuracy and area of use
  (`projinfo`); the log must record *which one* ran, and why.
- **Convention hazards**: EPSG:4326 vs `OGC:CRS84` axis-order confusion (lat/lon vs lon/lat) is a
  live, still-open hazard across the geospatial ecosystem — axis order must be an explicit
  property of the recorded operation.
- **Preserve-native precedent**: the STAC catalog `projection` extension keeps each asset's native
  system at the per-asset level because forced re-projection "can be lossy" and breaks no-copy,
  cloud-native workflows.
- **Serializable operation records**: PROJ's pipeline operator (`+proj=pipeline +step ... +step
  ...`) and the PROJJSON specification (a lossless JSON encoding of WKT2:2019 / ISO-19162:2019
  coordinate operations) are the reference pattern for persisting "exactly what operation sequence
  was applied."

A geospatial domain enabling this plugin keys Component 1's capture to EPSG codes (or WKT2 strings
where no code exists) and Component 2's log entries to EPSG operation codes or PROJJSON records —
the general decision above, instantiated with that domain's registry and tooling.

## Links

- ADR file: `docs/adr/adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-024
