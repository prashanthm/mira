# ADR-030: Graph + Vector Fusion (Graph RAG)

## Status

Accepted

## Context

Vector retrieval ([ADR-028](./adr-028-hybrid-retrieval.md)) finds text that looks like the
question; it does not know that two chunks describe the same entity, that a ledger account is
referenced across documents, or that a question about one section should pull the neighborhood of
a specific canonical entity. Mira already maintains the structures that encode this: the
knowledge-graph spine ([ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md)), canonical
typed identity nodes from deterministic-key-first entity resolution
([ADR-022](./adr-022-canonical-entity-resolution-and-identity.md)), and the ADR-021
knowledge-graph store role. The open question was how graph and vector retrieval fuse into one
entity-aware grounding path.

Phase C makes the whole semantic stack concrete in the `semantic/` package: the resolver and
canonical nodes (`entities.py`, ADR-022), the in-memory triple-store spine with builders from both
demo connectors (`kg.py`, ADR-027), the entity + pluggable-aspect catalog (`catalog.py`,
[ADR-026](./adr-026-catalog-service-design.md)), and measurement/derived conflict surfacing
(`conflicts.py`, [ADR-025](./adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md)).
Fusion is the layer that joins that spine to the ADR-028 retriever. The demo domains give it a
concrete test: `research` docs contribute Document/Section entities with containment and
cross-reference edges; the `finance` ledger contributes Account/Category/Entry entities with
posting edges — exactly the multi-source entity joins ADR-022 canonicalizes.

## Decision Drivers

1. **Entity-blindness of pure vector retrieval** — hits must resolve to canonical identities so
   related evidence connects across chunks and sources.
2. **The spine already exists (ADR-022/ADR-027)** — fusion should *join* retrieval to the
   canonical graph, not run a second extraction pipeline that re-derives entities.
3. **Deterministic, offline, structural (ADR-045)** — the reference fusion must work with no
   model calls, so graph context comes from graph structure, not generated summaries.
4. **Provenance on every claim (ADR-025/[ADR-040](./adr-040-decision-trace-audit.md))** — graph-
   derived context must carry edge provenance just as retrieval hits carry source ids.
5. **Never lose retrieval evidence** — a hit that fails entity resolution must still be returned;
   fusion adds context, it must not filter.

## Research & Rubric

Scored structural fusion over the existing ADR-022/ADR-027 spine against a document-KG extraction
pipeline (model-extracted entities/relations plus community summaries) and against graph-only
retrieval, on determinism/offline testability, duplication of the semantic spine, extraction cost
and quality risk, and provenance fidelity. Structural fusion wins for the reference
implementation: it reuses the canonical spine as-is, is fully deterministic, and keeps every
context edge attributable; the extraction-heavy variant is deferred, not rejected outright.

## Decision

Adopt **deterministic, structural graph + vector fusion over the canonical spine**:
`GraphVectorFusion` in `semantic/fusion.py`, joining the ADR-028 `HybridRetriever`, the ADR-027
`KnowledgeGraph`, and the ADR-022 `EntityResolver`.

**1. Query-time fusion contract.**
`answer(query, k)` runs hybrid retrieval, then expands each hit: the hit's anchor/metadata key is
resolved to a canonical entity via a **non-creating lookup** (resolution never mutates identity as
a retrieval side effect), and the entity's **1-hop graph neighborhood** is appended as
`GraphContext` records — neighbor entity id and type, predicate, edge direction, and the edge's
provenance. Each `FusedHit` carries both the retrieval score and the graph provenance; retrieval
order is preserved, and hits with no resolvable entity return with empty context rather than
being dropped.

**2. The graph is built by the spine's builders, not by extraction.**
`graph_from_docs` (Document/Section nodes, `has_section` containment, `mentions` cross-reference
edges where one section's body names another's title) and `graph_from_ledger` (Account/Category/
Entry nodes, `posted_to`/`in_category` edges with currency-bearing provenance) populate the
knowledge graph from the parsed connector documents through the shared resolver — so vector hits
and graph nodes agree on canonical identity by construction (the section anchor is the shared
deterministic key).

**3. Provenance flows into traces.**
Every context edge carries the connector `Provenance` it was built from (`source#anchor` for
docs, source + currency unit for ledger edges), so entity-level claims surfaced through fusion
remain attributable end-to-end (ADR-025, ADR-040).

**Rejected alternatives:**

- **Document-KG extraction pipeline (model-extracted entities/relations, community-detected
  topic summaries)** — Rejected for the reference implementation: requires model calls in the
  offline path, duplicates the ADR-022/ADR-027 spine with a parallel, lower-trust entity space,
  and its extraction quality bar is unvalidated. Revisit as a deferred enrichment (below).
- **Graph-only retrieval (traverse from resolved query entities, skip vectors)** — Rejected:
  loses the paraphrase/lexical recall ADR-028 provides and fails open-ended queries that name no
  known entity; fusion keeps vectors primary and adds the graph as context.
- **Filtering hits to graph-resolvable ones** — Rejected: fusion must never discard retrieval
  evidence; an unresolved hit with empty context is strictly more informative than a dropped one.

## Consequences

### Becomes Easier

- Answers ground in *entities*, not just text: a section hit arrives with its containing
  document, cross-referenced sections, and (for ledger-linked entities) posting structure — each
  with citable provenance.
- Multi-source joins ride the ADR-022 crosswalk: once a source's keys feed the resolver, its
  entities join fusion context with no fusion-side changes.
- The whole path — retrieve, resolve, traverse — is deterministic and offline, so graph-RAG
  behavior is eval-gated like everything else (ADR-045).
- `subgraph(entity_id, depth)` gives callers a bounded widening primitive for the deferred
  ADR-029 graph-neighborhood re-query strategy.

### Becomes Harder

- Fusion quality is bounded by builder coverage: relationships nobody encoded as edges
  (`mentions` detection is deliberately trivial — exact title references) produce no context.
- The shared-resolver discipline is load-bearing: index keys and graph keys must come from the
  same resolution space, or lookups silently miss (mitigated: lookup is deterministic and the
  miss path is explicit and tested).
- 1-hop context is a fixed horizon; deeper traversal exists (`subgraph`) but ranking
  graph-derived context against vector-derived context beyond 1 hop is unresolved.

## Deferred

- **Graph/vector store backends** — the in-memory `KnowledgeGraph` and indexes swap for managed
  graph and vector engines behind the same shapes under `providers/`, per the ADR-021 role seam
  and per-profile defaults ([ADR-047](./adr-047-deployment-profiles-and-packaging.md)).
- **Model-backed enrichment** — entity/relation extraction from free text and precomputed
  topic-community summaries, feeding the *same* spine through the resolver (never a parallel
  entity space), behind the same builder pattern.
- **Context ranking beyond 1 hop** — scoring graph-derived context against retrieval scores for
  deeper traversals.
- **Live-model grading/rewriting for graph-aware re-query** — the ADR-029 hooks, widened to
  choose graph neighborhoods as a corrective strategy.

## Applies To

- `src/mira/semantic/` — this decision's home (`fusion.py`, with `entities.py`/`kg.py`/
  `catalog.py`/`conflicts.py` as the spine it joins).
- `src/mira/retrieval/` — the ADR-028 pipeline fused here.
- [ADR-022](./adr-022-canonical-entity-resolution-and-identity.md) — canonical identity nodes and
  the non-creating lookup discipline.
- [ADR-027](./adr-027-knowledge-graph-semantic-catalog-spine.md) — the graph spine fusion
  traverses.
- [ADR-025](./adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md) /
  [ADR-040](./adr-040-decision-trace-audit.md) — provenance contracts context records honor.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — offline eval gate the deterministic
  design serves.

## Links

- ADR file: `docs/adr/adr-030-graph-vector-fusion.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-030
