# ADR-030: Graph + Vector Fusion (Graph RAG)

Status: Proposed

## Context

Vector retrieval (ADR-028) finds text that looks like the question; it does not know that two
chunks describe the same entity, that an account in the ledger is referenced by three design docs,
or that a question about "vendor spend" should pull the neighborhood of a specific canonical
entity. Mira already maintains the structures that encode this: the RDF/OWL knowledge-graph spine
(ADR-027), canonical identity nodes from entity resolution (ADR-022), and the ADR-021
knowledge-graph store role. The open question is how graph and vector retrieval fuse into one
entity-aware grounding path.

The current direction is a document-KG approach: extract entities and relations from the ingested
corpora into a document-level knowledge graph with explicit source linking (every node/edge cites
the chunks it was derived from), apply community detection to form topic-level summaries, and at
query time combine graph traversal (entity neighborhoods, community summaries) with the ADR-028
hybrid results. Open sub-questions include the extraction pipeline's cost and quality bar, how
graph-derived context is ranked against vector-derived context, whether community summaries are
precomputed or on-demand, and how graph provenance flows into decision traces (ADR-040) so
entity-level claims stay attributable.

The demo domains give the fusion a concrete test: `research` docs cross-reference people,
projects, and decisions, while the `finance` ledger contributes typed entities (accounts,
vendors, periods) — exactly the multi-source entity joins that ADR-022 canonicalizes and ADR-025
requires to surface conflicts rather than silently merge.

## Decision (pending)

This ADR will select the graph-plus-vector fusion approach: the document-KG extraction and
source-linking model, community detection usage, and the query-time fusion/ranking contract. It
builds on the planned `retrieval/` package (as the fusion layer over the ADR-028 pipeline), the
docs-connector corpus as the first extraction target, and the ADR-027 graph spine and ADR-022
canonical identity nodes as the entity backbone.

Planned phase: C (retrieval, with ADR-028 and ADR-029).
