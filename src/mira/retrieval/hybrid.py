"""Hybrid retrieval: dense + sparse fused with Reciprocal Rank Fusion (ADR-028).

Dense (embedding cosine) retrieval catches paraphrase and morphological variance;
sparse (BM25) catches exact identifiers and rare terms. :class:`HybridRetriever`
runs both and fuses their rankings with RRF — ``score = Σ 1/(rrf_k + rank)`` over
the rankers that returned the document — which needs no score calibration between
heterogeneous rankers. An optional ``reranker`` hook runs after fusion; the
in-tree default is none, and a cross-encoder reranker plugs into the same hook
later without changing the pipeline contract (ADR-028 deferred item).

Fused hits keep the underlying metadata (provenance ``source_id`` travels with
every result — ADR-025/ADR-040) and add per-ranker ranks (``dense_rank`` /
``sparse_rank``) so downstream grading (ADR-029) can inspect ranker agreement.

``index_corpus`` indexes a :class:`~mira.connectors.docs.DocsDocument`'s sections —
the docs-connector corpus is the first indexed knowledge base.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mira.connectors.docs import DocsDocument
from mira.retrieval.protocols import SearchHit, VectorIndex
from mira.retrieval.sparse import Bm25Index

Reranker = Callable[[str, list[SearchHit]], list[SearchHit]]

_CANDIDATE_MULTIPLIER = 4


class HybridRetriever:
    """Dense + sparse retrieval fused with Reciprocal Rank Fusion (ADR-028)."""

    def __init__(
        self,
        dense: VectorIndex,
        sparse: Bm25Index,
        *,
        rrf_k: int = 60,
        reranker: Reranker | None = None,
    ) -> None:
        if rrf_k <= 0:
            raise ValueError(f"rrf_k must be positive, got {rrf_k}")
        self.dense = dense
        self.sparse = sparse
        self.rrf_k = rrf_k
        self.reranker = reranker

    def add(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        """Index one document in both the dense and the sparse ranker."""
        self.dense.add(doc_id, text, metadata)
        self.sparse.add(doc_id, text, metadata)

    def search(self, query: str, k: int) -> list[SearchHit]:
        """Return up to *k* RRF-fused hits, best first (ties broken by doc_id).

        Each ranker contributes a candidate pool larger than *k* so a document
        ranked just outside the top-k by both rankers can still fuse into the
        top-k. The optional reranker hook runs on the fused list.
        """
        if k <= 0:
            return []
        pool = k * _CANDIDATE_MULTIPLIER
        dense_hits = self.dense.search(query, pool)
        sparse_hits = self.sparse.search(query, pool)

        fused: dict[str, dict[str, Any]] = {}
        for source, hits in (("dense", dense_hits), ("sparse", sparse_hits)):
            for rank, hit in enumerate(hits, start=1):
                entry = fused.setdefault(
                    hit.doc_id, {"hit": hit, "score": 0.0, "dense_rank": None, "sparse_rank": None}
                )
                entry["score"] += 1.0 / (self.rrf_k + rank)
                entry[f"{source}_rank"] = rank

        results = [
            SearchHit(
                doc_id=doc_id,
                score=entry["score"],
                text=entry["hit"].text,
                metadata={
                    **entry["hit"].metadata,
                    "dense_rank": entry["dense_rank"],
                    "sparse_rank": entry["sparse_rank"],
                },
            )
            for doc_id, entry in fused.items()
        ]
        results.sort(key=lambda hit: (-hit.score, hit.doc_id))
        results = results[:k]
        if self.reranker is not None:
            results = self.reranker(query, results)
        return results


def index_corpus(
    retriever: HybridRetriever, document: DocsDocument, *, source_id: str | None = None
) -> int:
    """Index every section of *document* into *retriever*; returns the section count.

    Each section is indexed under its anchor (``doc_id = anchor``) with
    ``title + body`` as the text; metadata carries the provenance ``source_id``
    (``<source>#<anchor>``, matching the docs connector's attribution shape) plus
    the anchor and title, so fused hits stay citable end-to-end (ADR-025, ADR-040).
    """
    source = source_id or document.headers.get("title") or "docs"
    for section in document.sections:
        retriever.add(
            section.anchor,
            f"{section.title}\n{section.body}",
            {
                "source_id": f"{source}#{section.anchor}",
                "anchor": section.anchor,
                "title": section.title,
            },
        )
    return len(document.sections)
