# ADR-028: Hybrid Retrieval Pipeline

## Status

Accepted

## Context

Mira's grounded answers depend on retrieval quality over the selectively-aggregated corpora that
[ADR-019](./adr-019-federation-strategy-aggregate-vs-federate.md) permits — in the demos, the
Markdown corpus ingested by the `docs` connector (the retrieval test bed) and derived artifacts
from the `ledger` connector. Pure dense (embedding) retrieval misses exact identifiers and rare
terms (doc titles, account codes, ADR numbers); pure sparse (lexical/BM25) retrieval misses
paraphrase and morphological variance ("override" vs "overridable"). Neither alone meets the
answer-grounding bar the eval gate ([ADR-045](./adr-045-eval-framework-ci-safety-gate.md)) asserts.

The storage decision ([ADR-021](./adr-021-storage-engine-selection.md)) already reserves a
**vector-index storage role behind an [ADR-002](./adr-002-provider-abstraction-pattern.md)
Protocol** with the engine as a per-profile default ("engine = config, not architecture"), and the
repo's boundary rules ([ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md),
[ADR-007](./adr-007-core-agent-stack-and-framework.md)) keep frameworks in `orchestration/` and
SDKs in `providers/`. Retrieval is also the substrate two sibling ADRs refine:
[ADR-029](./adr-029-agentic-rag.md) wraps this pipeline in a corrective loop, and
[ADR-030](./adr-030-graph-vector-fusion.md) fuses it with the knowledge graph. This ADR fixes the
base pipeline contract those two build on.

## Decision Drivers

1. **Complementary failure modes** — dense and sparse retrieval fail on disjoint query classes;
   the demo corpora exhibit both classes.
2. **ADR-021's vector-index role seam** — retrieval must sit behind Protocols so engines
   (pgvector, OpenSearch, a dedicated vector DB) stay per-profile defaults, never architecture.
3. **Offline-testable reference implementations (ADR-045)** — the eval gate runs fully offline,
   so the in-tree pipeline must be deterministic and dependency-free.
4. **Provenance end-to-end ([ADR-025](./adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md),
   [ADR-040](./adr-040-decision-trace-audit.md))** — every retrieved chunk must carry source
   identifiers so decision traces can cite it.
5. **Calibration-free fusion** — dense cosine scores and BM25 scores live on incomparable scales;
   the fusion rule must not require cross-ranker score calibration.

## Research & Rubric

Scored hybrid dense+sparse with Reciprocal Rank Fusion against dense-only, sparse-only, and
score-interpolation fusion (weighted sum of normalized scores) on recall over the demo corpus,
calibration burden, implementation cost, and fit to the ADR-021 Protocol seam. RRF hybrid wins:
it recovers both single-ranker failure classes, is rank-based (no score calibration or per-corpus
weight tuning), and is the established default in production hybrid-search engines.

## Decision

Adopt a **hybrid dense + sparse retrieval pipeline fused with Reciprocal Rank Fusion, behind
Protocol seams, with an in-tree dependency-free reference implementation** — the `retrieval/`
package.

**1. The seam: `retrieval/protocols.py`.**
`Embedder` (`embed(text) -> tuple[float, ...]`) and `VectorIndex` (`add(doc_id, text, metadata)` /
`search(query, k) -> list[SearchHit]`) are the ADR-021 vector-index role's Protocols. `SearchHit`
is a frozen dataclass carrying `doc_id`, `score`, `text`, and a `metadata` dict — provenance
(`source_id`, section anchor, title) travels with every hit.

**2. In-memory reference implementations, dependency-free by design.**
`HashEmbedder` embeds text deterministically (token + character-trigram features CRC32-hashed into
fixed buckets, L2-normalized — stable across processes, unlike Python's randomized `hash()`);
`InMemoryVectorIndex` performs cosine search over stored vectors; `Bm25Index` is a standard Okapi
BM25 lexical index (`k1`/`b` params, smoothed always-positive idf) with the same add/search
surface. Trigram features give the dense side morphological tolerance the exact-token sparse side
lacks — the complementary signal the fusion relies on.

**3. Fusion: `HybridRetriever` with RRF.**
Both rankers run per query; documents are fused by `score = Σ 1/(rrf_k + rank)` over the rankers
that returned them (`rrf_k` a constructor param, default 60), ties broken deterministically by
doc_id. Fused hits keep the underlying metadata and add per-ranker ranks
(`dense_rank`/`sparse_rank`) so downstream grading (ADR-029) can inspect ranker agreement. An
optional `reranker: Callable[[query, hits], hits]` hook runs after fusion.

**4. Corpus indexing: `index_corpus(retriever, docs_document)`.**
Indexes a `DocsDocument`'s sections — `doc_id` = section anchor, text = title + body, metadata
carries the provenance `source_id` (`<source>#<anchor>`, the docs connector's attribution shape).
The docs-connector corpus is the first indexed knowledge base; golden retrieval evals
(`evals/test_retrieval_evals.py`) assert recall@k over it per ADR-045.

**Rejected alternatives:**

- **Dense-only or sparse-only retrieval** — Rejected: each fails a query class the demo corpora
  exhibit (sparse returns nothing for morphological variants; dense is confused by
  character-level smearing that exact-term match resolves); the in-tree tests demonstrate both
  failures and their fusion recovery.
- **Score-interpolation fusion (weighted sum of normalized scores)** — Rejected: requires
  cross-ranker score calibration and per-corpus weight tuning; RRF is rank-based and
  calibration-free.
- **Cross-encoder re-ranking as a core stage** — Rejected as a *requirement*: it needs a model
  call, which the offline reference pipeline cannot assume. Kept as the `reranker` hook (see
  Deferred).

## Consequences

### Becomes Easier

- Queries that defeat one ranker are recovered by the other; fusion never scores below the better
  ranker on the golden set (asserted in tests).
- Backends swap per profile: a pgvector/OpenSearch implementation of the same Protocols replaces
  the in-memory pair without touching `HybridRetriever` or its callers.
- Retrieval results are citable end-to-end — `source_id` metadata feeds ADR-025 conflict
  surfacing and ADR-040 decision traces unchanged.
- The eval gate runs the real pipeline offline and deterministically.

### Becomes Harder

- Two indexes to populate and keep consistent per corpus (`index_corpus` hides this for the docs
  path, but every new corpus must index both sides).
- RRF's rank-only signal discards score magnitude: a marginal rank-1 and a dominant rank-1
  contribute identically, so confidence estimation needs the per-ranker metadata, not the fused
  score alone.
- The hash embedder is a lexical-feature stand-in, not a semantic model — true paraphrase
  ("remuneration" vs "salary") is out of its reach; profiles needing that must swap in a real
  embedding backend.

## Deferred

- **pgvector / OpenSearch / dedicated-vector-DB backends** — `providers/`-level implementations
  of the same `Embedder`/`VectorIndex` Protocols, selected per deployment profile
  ([ADR-047](./adr-047-deployment-profiles-and-packaging.md)); no pipeline change required.
- **Cross-encoder re-ranking** — plugs into the existing `reranker` hook as a model-backed
  callable once a reranking model is provisioned.
- **Query expansion and multi-KB routing** — additional corpora (long-term memory tier,
  [ADR-017](./adr-017-memory-architecture.md)/[ADR-018](./adr-018-memory-integrity-and-embedding-versioning.md))
  mount as additional `HybridRetriever` instances; a routing layer above them is future work.

## Applies To

- `src/mira/retrieval/` — this decision's home (`protocols`, `inmemory`, `sparse`, `hybrid`).
- [ADR-021](./adr-021-storage-engine-selection.md) — vector-index storage role this pipeline runs behind.
- [ADR-029](./adr-029-agentic-rag.md) / [ADR-030](./adr-030-graph-vector-fusion.md) — sibling
  decisions building on this pipeline contract.
- [ADR-025](./adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md) /
  [ADR-040](./adr-040-decision-trace-audit.md) — provenance consumers of hit metadata.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — golden retrieval evals
  (`evals/test_retrieval_evals.py`) gating this pipeline.

## Links

- ADR file: `docs/adr/adr-028-hybrid-retrieval.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-028
