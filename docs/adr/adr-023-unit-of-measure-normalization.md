# ADR-023: Measurement Normalization (Pluggable Unit-of-Measure Normalizer)

## Status

Accepted

## Context

The accepted federation strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))
queries source data **at the source** by default — document corpora, transaction ledgers,
warehouses, streams, historians — and names the semantic spine as the layer that reconciles
identity, units, and reference frames **above** sources, not a rewrite of the sources themselves.
The sibling entity ADR ([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)) resolves
canonical typed entities in the ADR-021 knowledge-graph store role; this ADR decides the companion
question for the same canonical entities — **how dimensioned quantities carried by those entities
are normalized to consistent units** regardless of source.

The generic concern is **any dimensioned quantity**. In the finance demo the dimension is
**currency**: two ledger entries in different currencies are not addable, and the `ledger`
connector already enforces this at the source boundary — `ledger.query` **rejects mixed-currency
aggregation** with an explicit error rather than returning a silently wrong sum, and every ledger
record's provenance carries its currency as the `units` field. In scientific and engineering
domains the dimension is a physical unit: length in feet on one source and meters on another,
pressure in psi vs kPa. Left unresolved, an agent comparing a quantity from one connector against
the "same" quantity from another has no structural guarantee it is comparing like with like —
silent unit mismatch across a system boundary is a well-documented, high-consequence failure class
(the 1999 Mars Climate Orbiter loss traced to exactly this: one subsystem emitting
pound-force-seconds while the consumer assumed newton-seconds).

Critically, this decision **cannot be made from a blank slate**. Tool responses already carry
units/reference-frame metadata per record (inherited mcp-server ADR-021, LLM-context metadata in
responses; surfaced in Mira as `Provenance.units` on every `SourceRecord`), so the semantic spine
must **consume and reconcile** that metadata for self-describing sources instead of re-deriving it.
The inherited decision's own Consequences section warns that if a second, independent computation
of the same context ever disagrees with the carried metadata, the result is "actively misleading —
worse than no metadata."

This ADR decides **how the fabric normalizes dimensioned quantities to canonical units across
sources** — the normalizer's shape, how it consumes vs. derives unit context, and when
normalization happens. It does not decide reference-frame transforms (a related but distinct
problem with its own audit-trail requirement, the explicit subject of
[ADR-024](./adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md)) or the
concrete graph ontology for canonical entities
([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md)).

## Decision Drivers

1. **Inherited metadata constraint** — the semantic spine must **consume and reconcile** the
   units metadata that connector/tool responses already carry for self-describing sources, not
   re-derive it independently; this is recorded as an inherited constraint.
2. **ADR-019's "every source is one connector" constraint** — normalization must not require
   funneling every source through any single platform's unit service to count as normalized; the
   fabric must cover each connector on its own terms.
3. **Unit dictionaries are a domain concern, not a fabric invention** — currencies have ISO 4217;
   science and healthcare have UCUM; several industries maintain sector-wide unit-of-measure
   standards (see Appendix). The normalizer must be **pluggable**: each domain supplies its
   dictionary; the fabric supplies the discipline. Inventing a fabric-global dictionary would
   duplicate existing, normative registries.
4. **Sources carry their own unit context at the point of origin** — the ledger connector carries
   a currency per entry; schema-rich formats carry a per-field unit attribute; warehouse columns
   carry declared types. Unit context is rarely absent, it just isn't uniformly surfaced.
5. **Non-destructive, auditable normalization (regulated settings)** — established practice keeps
   data unconverted at rest and normalizes **on read**, driven by a recorded conversion
   descriptor, so a mis-specified unit context can be corrected without re-ingestion. The fabric's
   approach must be consistent with this, not introduce a destructive convert-and-discard pattern.
6. **ADR-022's canonical entities need a place to carry normalized measurements** — canonical
   typed nodes ([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)) are the natural
   anchor for normalized values once resolved; measurement normalization and entity resolution are
   sibling decisions operating on the same canonical layer.

## Research & Rubric

Scored (1) a dedicated, pluggable normalization component keyed to a domain-supplied unit
dictionary that consumes carried units metadata from self-describing sources and independently
applies the same dictionary to other sources' own carried unit tags, (2) re-deriving unit context
independently for all sources, (3) convert-at-ingest with canonical-only storage, and (4) no
dedicated component (ad hoc per-agent conversion) — against fit to the inherited
consume-not-re-derive constraint, use of existing normative dictionaries, fit to ADR-019's
query-in-place default, coverage across all connectors, avoidance of the
"two-independent-paths-disagree" failure the inherited decision itself flags,
auditability/reversibility, and operational cost. Option 1 wins — it is the only option that
satisfies the inherited constraint, reuses rather than duplicates the dictionaries domains already
maintain, and avoids introducing a second, potentially-disagreeing computation of the same context.

## Decision

Adopt a **dedicated measurement-normalization component, pluggable per domain**: it is keyed to a
**domain-supplied unit dictionary**, **consumes** the units metadata that self-describing sources
already carry, **independently applies the same dictionary** to other sources' own carried unit
tags, and normalizes **on read** without mutating source values.

**1. One shared dictionary per domain, not a fabric-invented one.**
The component keys to whatever normative dictionary the domain already has — ISO 4217 currency
codes for the finance demo, UCUM-style unit codes for scientific domains, a sector standards
body's unit-of-measure dictionary where one exists (Appendix). This applies uniformly across every
connector in that domain. No fabric-specific unit dictionary is introduced.

**2. Self-describing sources: consume, do not re-derive.**
For any value whose connector/tool response already carries authoritative unit context — the
`ledger` connector's per-record currency in `Provenance.units`, or an upstream MCP server's
response-level metadata envelope (inherited mcp-server ADR-021) — the component reads that carried
context as the source-unit truth. It does **not** independently recompute it — that computation
already happened once, at the connector/MCP boundary, and a second independent computation risks
silently disagreeing with the first (the exact "actively misleading" failure the inherited
decision's own Consequences section names).

**3. Other sources: dictionary-driven conversion off the source's own carried unit tag.**
For sources with no pre-computed metadata envelope, the component converts using the unit tag the
source itself carries at the point of origin — a per-column unit attribute in a warehouse schema,
an engineering-units field on a time-series tag, a per-field annotation in a document's
front-matter — against the domain dictionary (step 1). Where a source carries no explicit unit
tag at all (free-text headers, ad hoc configurations), the component applies a documented,
per-connector **declared default** as a provisional stopgap, flagged as such — never a silent
guess (Mira's connector layer already normalizes missing units to an explicit `unknown` sentinel
rather than a hole). Concrete default-unit governance (who declares it, how discrepancies are
surfaced) is a semantic-spine feature-spec concern, not fixed here.

**4. Normalize on read; never mutate source values.**
Normalization happens when a value is returned to a specialist or user: source values are never
overwritten, and a canonical value is always re-derivable from its source value plus the recorded
conversion. **Non-convertible dimensions fail loudly rather than normalize silently** — the
finance demo's rule that mixed-currency aggregation is rejected (currency conversion requires an
explicit, dated rate — a transform, not a static unit conversion; see ADR-024) is the model: a
normalizer must never fabricate comparability that the dictionary alone cannot justify.

**5. Canonical unit choice is per quantity and per domain, not fixed here.**
Which unit is canonical for each quantity (which currency a portfolio reports in; meters vs feet
for length) is an implementation decision for the domain's feature spec — this ADR fixes the
**pluggable-dictionary shape**, the **consume-vs-derive split**, and the **normalize-on-read
discipline**, not the specific canonical unit table.

**6. Anchors to ADR-022's canonical entities.**
Normalized measurements attach to the canonical typed nodes
([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)) once an entity is resolved,
consistent with that ADR's canonical-node-plus-provenance pattern — the two decisions operate on
the same canonical layer, not parallel ones.

**Rejected alternatives:**

- **Re-derive unit context independently for all sources, including self-describing ones** —
  Rejected: directly contradicts the inherited consume-not-re-derive constraint; produces two
  independent computation paths for the same data that can silently drift apart — exactly the
  "actively misleading" failure the inherited decision's Consequences section names.
- **Convert-at-ingest, canonical-only storage** — Rejected: requires persisting a converted copy
  of every dimensioned value fabric-wide, in tension with the accepted ADR-019 query-in-place
  default for operational and system-of-record sources; weakens auditability, since re-verifying a
  canonical value against its original source unit is harder once ingestion has discarded or
  separated the source value.
- **No dedicated component (ad hoc per-agent conversion)** — Rejected: no shared dictionary, no
  structural guarantee of consistency across agents, and no persisted record of which conversion
  (if any) was applied — the class of silent, boundary-crossing unit mismatch that produced the
  Mars Climate Orbiter loss, now with no fabric-level defense at all.

## Consequences

### Becomes Easier

- Specialists and users receive consistent units regardless of source — a monetary amount or
  physical quantity is comparable across connectors without per-agent conversion logic, and
  non-comparable quantities are rejected loudly instead of silently summed.
- Self-describing sources' normalization work is not duplicated — the fabric reuses the carried
  metadata computation rather than re-implementing it.
- Adding a new source only requires mapping its native unit-tagging convention into the domain's
  shared dictionary — no new dictionary, no rework of existing paths.
- Normalization is auditable and reversible: source values are never overwritten, and every
  canonical value is traceable back to its source value and the conversion applied.

### Becomes Harder

- Sources with no explicit unit tag require a declared-default fallback and governance for
  surfacing discrepancies — this is ongoing operational surface, not a one-time build, and its
  concrete mechanics are deferred to a feature spec.
- The fabric now carries a load-bearing dependency on the carried-metadata contract staying
  accurate — if an upstream change alters how connector metadata is populated without this ADR's
  consuming logic being updated in lockstep, normalization for that source silently breaks; the
  two decisions must be read together, not independently.
- Canonical unit choice per quantity is left open by this ADR, meaning a follow-on domain
  feature-spec decision is required before implementation can start — this ADR alone does not
  unblock coding.

## Applies To

- Semantic spine — this decision's primary home; features derive from it once ratified.
- `src/mira/fabric/` — federation engine returning normalized values across sources.
- `src/mira/connectors/` — source adapters that supply source-unit context (carried `units` in
  provenance, or native tags) to the normalization component; the `ledger` connector's
  mixed-currency rejection is the in-tree proof of the fail-loudly rule.
- Catalog ([ADR-026](./adr-026-catalog-service-design.md)) — records which conversion was applied
  to a given canonical measurement.
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — federation strategy this
  normalization component operates above.
- [ADR-020](./adr-020-source-connector-architecture.md) — connector architecture supplying source
  records and native unit tags.
- [ADR-021](./adr-021-storage-engine-selection.md) — knowledge-graph store role canonical
  measurements are anchored in via ADR-022's canonical nodes.
- [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) — canonical entity resolution;
  normalized measurements attach to the typed nodes this ADR resolves.
- [ADR-024](./adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md) —
  reference-frame preservation & transformation audit trail — sibling semantic-spine decision
  covering frame *transforms* (including currency conversion), distinct from this ADR's
  static-unit-conversion scope.
- Inherited: mcp-server ADR-021 — the response-metadata mechanism this ADR consumes for
  self-describing sources rather than re-deriving.

## Appendix — Domains with a normative standards-body dictionary

Some sectors maintain a single, cross-vendor unit-of-measure standard (often harmonizing several
predecessor registries), and vendor platforms in those sectors build their unit services on it.
Where a domain has such a standard — ISO 4217 for currencies, UCUM for clinical/scientific units,
or a sector consortium's published unit dictionary — the normalizer **must key to it** rather than
invent a parallel dictionary: the standard is the dictionary plugged into this ADR's component,
and conformance with the sector's own tooling comes for free. The dedicated-component decision
above is unchanged by which dictionary a domain plugs in.

## Links

- ADR file: `docs/adr/adr-023-unit-of-measure-normalization.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-023
