# ADR-028: Hybrid Retrieval Pipeline

Status: Proposed

## Context

Mira's grounded answers depend on retrieval quality over the selectively-aggregated corpora that
ADR-019 permits — in the demos, the Markdown documents ingested by the `research` docs connector
and derived artifacts from the `finance` CSV ledger. Pure dense (embedding) retrieval misses
exact identifiers, code names, and rare terms that matter in both demo domains (ticket IDs, doc
titles, account codes); pure sparse (lexical/BM25) retrieval misses paraphrase and conceptual
matches. Neither alone meets the answer-grounding bar the eval gate (ADR-045) asserts.

The current direction is a hybrid pipeline: dense + sparse retrieval fused with Reciprocal Rank
Fusion (RRF), followed by cross-encoder re-ranking of the fused candidate set, with query
expansion for short or underspecified queries and support for multiple knowledge bases (per-domain
corpora plus the long-term memory tier from ADR-017/018). Open sub-questions include the fusion
weighting, where re-ranking runs (inline vs. a separate service), how per-KB routing is decided,
and how retrieval results carry provenance so decision traces (ADR-040) can cite them.

Retrieval is also the substrate two sibling ADRs refine: ADR-029 wraps this pipeline in agentic
retrieve-critique-refine loops, and ADR-030 fuses it with the knowledge graph. This ADR therefore
fixes the base pipeline contract those two build on.

## Decision (pending)

This ADR will select the retrieval architecture: hybrid dense + sparse with RRF fusion,
cross-encoder re-ranking, query expansion, and multi-KB routing — confirming or revising the
current direction. It builds on the planned `retrieval/` package as the home for the pipeline
(behind the ADR-002 Protocol seams, engines per ADR-021's vector-index and relational roles) and
on the docs-connector corpus as the first indexed knowledge base. Retrieved chunks must carry
source identifiers compatible with ADR-025 conflict surfacing and ADR-040 attribution.

Planned phase: C (retrieval, with ADR-029 and ADR-030).
