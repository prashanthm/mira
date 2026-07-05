"""Tests for hybrid dense+sparse retrieval with RRF fusion (ADR-028).

Uses the handbook fixture as the retrieval test bed: fusion must recover queries
that defeat one ranker alone (term-mismatch beats sparse; exact-term beats a
trigram-smeared dense ranking), and the reranker hook must run after fusion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.connectors.docs import parse_markdown
from mira.retrieval.hybrid import HybridRetriever, index_corpus
from mira.retrieval.inmemory import InMemoryVectorIndex
from mira.retrieval.sparse import Bm25Index

FIXTURE = Path(__file__).parent / "fixtures" / "handbook.md"


def _handbook_retriever(**kwargs) -> HybridRetriever:
    retriever = HybridRetriever(InMemoryVectorIndex(), Bm25Index(), **kwargs)
    count = index_corpus(retriever, parse_markdown(FIXTURE.read_text()), source_id="handbook")
    assert count == 3
    return retriever


def test_index_corpus_indexes_sections_with_provenance():
    retriever = _handbook_retriever()
    hits = retriever.search("middleware ordering chokepoint", 1)
    assert hits[0].doc_id == "middleware-ordering"
    assert hits[0].metadata["source_id"] == "handbook#middleware-ordering"
    assert hits[0].metadata["anchor"] == "middleware-ordering"
    assert hits[0].metadata["title"] == "Middleware Ordering"


def test_fused_hits_carry_per_ranker_ranks():
    hits = _handbook_retriever().search("middleware ordering chokepoint", 1)
    assert hits[0].metadata["dense_rank"] == 1
    assert hits[0].metadata["sparse_rank"] == 1


def test_fusion_recovers_term_mismatch_query_that_defeats_sparse():
    # Plural forms match nothing exactly: BM25 alone returns no evidence at all,
    # while the trigram dense ranker still lands the right section — and RRF
    # fusion carries that through.
    retriever = _handbook_retriever()
    query = "middlewares orderings chokepoints"
    assert retriever.sparse.search(query, 3) == []
    assert retriever.search(query, 3)[0].doc_id == "middleware-ordering"


def test_fusion_recovers_exact_term_query_that_defeats_dense():
    # Trigram smearing: four "-esting" tokens pull the dense ranker to the wrong
    # doc, but the exact-term sparse ranking corrects the fused order.
    retriever = HybridRetriever(InMemoryVectorIndex(), Bm25Index())
    retriever.add("smear", "resting nesting jesting besting", {})
    retriever.add("exact", "testing the release pipeline requires patience and coverage", {})
    assert retriever.dense.search("testing", 2)[0].doc_id == "smear"
    assert retriever.sparse.search("testing", 2)[0].doc_id == "exact"
    assert retriever.search("testing", 2)[0].doc_id == "exact"


def test_rrf_fusion_beats_either_ranker_alone_on_recall():
    goldens = [
        ("middleware ordering chokepoint", "middleware-ordering"),
        ("deployment profile env override", "deployment-profiles"),
        ("offline pytest echo provider", "testing-standards"),
        ("middlewares orderings chokepoints", "middleware-ordering"),  # defeats sparse
    ]
    retriever = _handbook_retriever()

    def recall_at_1(search) -> int:
        score = 0
        for query, expected in goldens:
            hits = search(query, 1)
            score += bool(hits) and hits[0].doc_id == expected
        return score

    fused = recall_at_1(retriever.search)
    dense_only = recall_at_1(retriever.dense.search)
    sparse_only = recall_at_1(retriever.sparse.search)
    assert fused == len(goldens)
    assert fused >= dense_only
    assert fused > sparse_only


def test_reranker_hook_runs_after_fusion():
    seen: list[str] = []

    def reverse_reranker(query, hits):
        seen.append(query)
        return list(reversed(hits))

    retriever = _handbook_retriever(reranker=reverse_reranker)
    hits = retriever.search("middleware ordering chokepoint", 3)
    assert seen == ["middleware ordering chokepoint"]
    assert hits[-1].doc_id == "middleware-ordering"


def test_fused_scores_are_reciprocal_rank_sums():
    retriever = _handbook_retriever()
    hits = retriever.search("middleware ordering chokepoint", 1)
    # Ranked first by both rankers: score = 2 / (rrf_k + 1).
    assert hits[0].score == pytest.approx(2.0 / 61.0)


def test_custom_rrf_constant_changes_scores():
    retriever = _handbook_retriever()
    sharp = HybridRetriever(retriever.dense, retriever.sparse, rrf_k=1)
    assert sharp.search("middleware ordering chokepoint", 1)[0].score == pytest.approx(1.0)


def test_non_positive_k_and_bad_rrf_k_are_rejected():
    retriever = _handbook_retriever()
    assert retriever.search("middleware", 0) == []
    with pytest.raises(ValueError):
        HybridRetriever(InMemoryVectorIndex(), Bm25Index(), rrf_k=0)
