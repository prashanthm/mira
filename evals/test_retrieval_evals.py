"""Golden retrieval evals (ADR-045): recall@k over the handbook corpus (ADR-028, ADR-029).

Offline goldens for the hybrid retrieval pipeline — each golden query must place
its expected section anchor in the fused top-k — plus one corrective-RAG golden:
a deliberately over-specific query whose evidence fails a deterministic relevance
grade on the first attempt and passes after the default query-relaxation rewrite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.connectors.docs import parse_markdown
from mira.retrieval.agentic import CorrectiveRetriever
from mira.retrieval.hybrid import HybridRetriever, index_corpus
from mira.retrieval.inmemory import HashEmbedder, InMemoryVectorIndex, tokenize
from mira.retrieval.protocols import SearchHit
from mira.retrieval.sparse import Bm25Index

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"

K = 2

# (golden query, expected section anchor in the top-K fused hits)
RETRIEVAL_GOLDENS = [
    ("middleware ordering chokepoint", "middleware-ordering"),
    ("deployment profile env override", "deployment-profiles"),
    ("offline pytest echo provider", "testing-standards"),
]


@pytest.fixture()
def retriever() -> HybridRetriever:
    document = parse_markdown((FIXTURES / "handbook.md").read_text())
    hybrid = HybridRetriever(InMemoryVectorIndex(HashEmbedder()), Bm25Index())
    assert index_corpus(hybrid, document, source_id="handbook") == 3
    return hybrid


@pytest.mark.parametrize(("query", "expected"), RETRIEVAL_GOLDENS, ids=[a for _, a in RETRIEVAL_GOLDENS])
def test_golden_recall_at_k(retriever, query, expected):
    hits = retriever.search(query, K)
    assert expected in [h.doc_id for h in hits], (
        f"expected {expected!r} in top-{K} for {query!r}, got {[h.doc_id for h in hits]}"
    )
    # Grounding contract: every golden hit stays citable (ADR-025/ADR-040).
    assert all(h.metadata.get("source_id", "").startswith("handbook#") for h in hits)


def _term_coverage_grader(query: str, hits: list[SearchHit]) -> bool:
    """Deterministic CRAG-style relevance grade: every query term must be evidenced."""
    if not hits:
        return False
    text = hits[0].text.lower()
    return all(term in text for term in tokenize(query))


def test_corrective_rag_recovers_an_overspecific_query(retriever):
    corrective = CorrectiveRetriever(retriever, grader=_term_coverage_grader, max_attempts=3)
    # "zzyqx" appears nowhere in the corpus: attempt 1 retrieves the right section
    # but fails the relevance grade; the default rewriter drops the
    # out-of-vocabulary token and attempt 2 passes.
    outcome = corrective.retrieve("middleware ordering chokepoint zzyqx")
    assert outcome.attempts == 2
    assert outcome.corrected is True
    assert outcome.budget_exhausted is False
    assert outcome.queries == (
        "middleware ordering chokepoint zzyqx",
        "middleware ordering chokepoint",
    )
    assert outcome.hits[0].doc_id == "middleware-ordering"
