# ADR-025: Derived-vs-Source Classification & Multi-Source Conflict Surfacing

## Status

Accepted

## Context

The accepted federation strategy ([ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md))
queries source data **at the source by default** — document corpora, transaction ledgers,
warehouses, streams, historians — and does so **per request**, not through a pre-reconciled
consolidated lake. Canonical entity resolution
([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)) then resolves those sources'
records to one canonical typed node via non-destructive crosswalk edges, never overwriting a
source record.

Resolving *identity* does not resolve *value agreement*. Once an entity is canonically identified,
the fabric can still be asked "what is this account's Q3 travel spend?" or "what does the policy
say about data retention?" and get **different answers from different sources at query time** —
two ledger extracts may disagree on a balance, or two document revisions may carry different
policy text for the same section. Two distinct problems compound here:

1. **Derived vs source is not tagged.** A source observation (a ledger entry as recorded, a
   document section as authored) and a derived value (a computed total over matched entries, a
   model-generated summary of a section, an analyst's categorization — a judgment call,
   potentially revised) are structurally different kinds of value, but nothing in the fabric's
   data model currently distinguishes them. The in-tree demos already exhibit both kinds:
   `ledger.query` returns a **computed total** derived from underlying entries, and a RAG answer
   over `docs.search` results is a **generated summary** derived from underlying sections. Mature
   source systems encode this distinction at the schema level — raw observations live in one
   record type, derived/interpreted products in another — and do not overwrite a prior derived
   product on revision, linking the new instance to the old one instead of discarding it.
2. **Multi-source disagreement has no surfacing mechanism.** Nothing today flags to the calling
   agent or user that two live sources returned different values for the same canonical attribute,
   let alone shows both values with their provenance. A fabric that silently picks a winner (most
   recent, or a fixed source-priority list) is indistinguishable, from the caller's point of view,
   from one that never had a conflict at all — which is unacceptable in the regulated settings
   this platform targets.

The initiative's success criteria require this resolution to exist as a **named component, not a
black box**, matching the same bar ADR-022 already applied to identity resolution. This ADR
decides **how the fabric tags derived vs source values and surfaces multi-source conflict** — not
the concrete graph/ontology representation
([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md)) or feature-level
confidence-threshold mechanics (a semantic-spine feature-spec concern).

## Decision Drivers

1. **Schema-level precedent in mature source systems** — raw observations vs derived/interpreted
   products are already separate record types in well-designed sources, and prior derived products
   are versioned-not-overwritten on revision; the fabric's model should generalize this pattern
   source-agnostically rather than inventing an incompatible one.
2. **ADR-019's query-in-place, multi-live-source default** — conflicts arise **at query time**
   across live sources, not at a single ingest/ETL step, so any conflict-handling model must work
   per-request rather than assuming a pre-reconciled lake.
3. **ADR-022's non-destructive precedent** — canonical identity resolution never overwrites a
   source record and never auto-merges uncertain matches; the value-conflict model must stay
   consistent with that same "never silently discard disagreeing data" posture.
4. **Regulated-setting auditability** — a silently-resolved conflict is unauditable: a reviewer
   cannot tell after the fact that a disagreement existed or which rule (if any) picked the answer
   the agent acted on.
5. **The "named component, not a black box" bar** — the same acceptance-criteria language ADR-022
   satisfied for identity applies here for value agreement; ad hoc, per-caller conflict handling
   (or none at all) fails it identically.

## Research & Rubric

Scored (1) a tagged value model (`kind` classification + source + provenance) with surfaced
multi-source conflicts, (2) silent latest-wins/source-priority resolution, (3)
statistical/probabilistic fusion into a single estimate, and (4) no distinction or conflict
handling (pass-through), against fit to the regulated/auditable setting, match to mature source
systems' own schema-level precedent, consistency with ADR-019's query-in-place model, consistency
with ADR-022's non-destructive identity precedent, agent/user decision quality, and implementation
cost. Option 1 wins — it is the only option consistent with both the schema-level
observation/derived split mature sources already draw and this initiative's own non-destructive,
auditable ADR-019/ADR-022 pattern, and it is squarely conflict-resolving-by-exposure in Bleiholder
& Naumann's data-fusion taxonomy rather than conflict-avoiding or conflict-ignoring.

## Decision

Adopt a **tagged value model with mandatory `kind` classification (`measurement` vs `derived`) and
explicit multi-source conflict surfacing** — the fabric never silently picks a winner among
disagreeing live sources.

**1. Every fabric-returned value for a canonical attribute carries a `kind` tag.**
Values resolved through the fabric for a canonical entity attribute (any typed entity per ADR-022)
are classified as `measurement` (a source observation as recorded — a ledger entry, a document
section as authored, a sensor/historian reading, a warehouse fact row) or `derived` (a computed or
interpreted value — a total computed over matched ledger entries, a model-generated summary of
document sections, an analyst's categorization or fitted estimate). Connectors tag values the same
way at the connector boundary regardless of whether the underlying source draws the distinction
itself — no source's records are left untagged because that source lacks the schema split.

**2. Derived values additionally carry derivation provenance.**
Every value tagged `derived` carries, at minimum: the source system(s) it was derived from, the
deriving process or interpreter reference where available (which computation, which model, which
analyst/process), and a timestamp/version. Where a source already preserves prior derived products
as linked-not-deleted instances, the fabric surfaces that version chain rather than only the
latest. The demo connectors are the in-tree proof shape: a `ledger.query` total carries the
matched-entry count and currency alongside the entries it was computed from; a generated summary
carries the section anchors it was grounded in.

**3. Multi-source conflicts are detected and surfaced, never silently resolved.**
When two or more live sources return different values for the same canonical attribute, the fabric
does not pick one. It returns **all** distinct values, each with its `kind` tag and provenance
(source, timestamp, deriving process where applicable), and flags the attribute as `conflicting`
in the response to the consuming agent/user. No fixed source-priority list, "most recent wins," or
statistical fusion is applied as a default suppression mechanism.

**4. No destructive collapsing — extends ADR-022's precedent to values, not just identity.**
Source records already are never overwritten by identity resolution (ADR-022); this ADR applies
the same rule one level up, at the attribute-value layer: a conflict is a first-class, inspectable
fact about the data, not an implementation detail the fabric hides.

**5. Scope boundary with ADR-027 and feature specs.**
This ADR decides the tagging model (`kind` + provenance) and the surface-don't-resolve rule for
conflicts. It does **not** decide the concrete graph/schema representation for these tags and
conflict metadata ([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md)) or the
confidence-band/threshold mechanics for what counts as a meaningful conflict versus
measurement-tolerance noise (a semantic-spine feature-spec concern, matching how ADR-022 left
concrete match thresholds to feature specs).

**Rejected alternatives:**

- **Silent latest-wins / fixed source-priority resolution** — Rejected: conflict-avoiding in
  Bleiholder & Naumann's taxonomy; hides the exact disagreement a regulated platform must expose,
  contradicts the versioned-not-overwritten precedent mature sources set for derived products, and
  a wrong priority ranking would silently produce a wrong answer with no audit trail.
- **Statistical/probabilistic fusion into a single estimate** — Rejected: requires an ongoing
  per-source reliability model (the most operationally expensive option), and even a well-tuned
  fused value still discards the underlying disagreement an agent or domain expert needs to apply
  judgment — substitutes one black box for another.
- **No distinction, no conflict handling (pass-through)** — Rejected: this is the current de facto
  state and fails the same "named component, not a black box" bar the acceptance criteria already
  ruled out for identity resolution in ADR-022.

## Consequences

### Becomes Easier

- Agents and domain experts can see when sources disagree and apply judgment, instead of silently
  inheriting a fixed rule's (possibly wrong) choice.
- Audits can inspect exactly which sources disagreed, by how much, and what (if anything) the
  agent or user chose — no invisible resolution logic to reverse-engineer after the fact.
- Adding a new connector only requires tagging its values `measurement`/`derived` at the boundary —
  no renegotiation of a global source-priority ranking every time ADR-019's connector set grows.
- Stays structurally consistent with ADR-022: neither identity resolution nor value reconciliation
  ever destructively discards disagreeing source data.

### Becomes Harder

- Every connector must classify its values as `measurement` or `derived` at ingestion/query time —
  this is real per-connector implementation surface, not a one-time build (free-text headers,
  warehouse extracts, and historian tags don't self-declare this the way a schema-split source
  does).
- Consuming agents and UIs must handle a `conflicting` response shape (multiple values +
  provenance) instead of a single scalar — every downstream consumer of a canonical attribute
  value has to be conflict-aware, which is more work than assuming one authoritative number.
- The fabric performs conflict detection on every multi-source query rather than deferring the
  cost to a background reconciliation job — a genuine query-time cost ADR-019's
  federation-by-default model imposes, flagged as an open risk pending real latency validation.

## Applies To

- Semantic spine — this decision's primary home; features derive from it once ratified.
- `src/mira/fabric/` — federation engine that must detect and surface conflicts at query time
  across live sources.
- `src/mira/connectors/` — source adapters responsible for tagging values `measurement`/`derived`
  at the boundary (the `docs` and `ledger` demos are the proof shapes).
- Catalog ([ADR-026](./adr-026-catalog-service-design.md)) — references derivation provenance and
  version chains.
- [ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) — federation strategy
  establishing the query-time, multi-live-source scenario this ADR's conflict surfacing operates
  within.
- [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) — canonical entity resolution
  this ADR's value-tagging model sits above, and whose non-destructive precedent it extends to
  values.
- [ADR-021](./adr-021-storage-engine-selection.md) — knowledge-graph store role this ADR's tagged
  values and conflict metadata are expected to be materialized in.
- [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) — owns the concrete graph
  ontology/property model for `kind` tags and conflict metadata this ADR requires.
- [ADR-023](./adr-023-unit-of-measure-normalization.md) /
  [ADR-024](./adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md) — sibling
  semantic-spine decisions on the same canonical entities and values this ADR classifies and
  reconciles.

## Links

- ADR file: `docs/adr/adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-025
