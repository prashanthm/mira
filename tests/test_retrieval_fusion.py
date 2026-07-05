"""Tests for graph + vector fusion over the handbook corpus (ADR-030)."""

from __future__ import annotations

from pathlib import Path

from mira.connectors.docs import parse_markdown
from mira.retrieval.hybrid import HybridRetriever, index_corpus
from mira.retrieval.inmemory import InMemoryVectorIndex
from mira.retrieval.sparse import Bm25Index
from mira.semantic.entities import EntityResolver
from mira.semantic.fusion import FusedHit, GraphVectorFusion
from mira.semantic.kg import graph_from_docs

FIXTURE = Path(__file__).parent / "fixtures" / "handbook.md"


def _fusion() -> tuple[GraphVectorFusion, HybridRetriever]:
    document = parse_markdown(FIXTURE.read_text())
    retriever = HybridRetriever(InMemoryVectorIndex(), Bm25Index())
    index_corpus(retriever, document, source_id="handbook")
    resolver = EntityResolver()
    graph = graph_from_docs(document, resolver, source_id="handbook")
    return GraphVectorFusion(retriever, graph, resolver), retriever


def test_hits_are_expanded_with_graph_context():
    fusion, _ = _fusion()
    results = fusion.answer("middleware ordering chokepoint", k=1)
    assert len(results) == 1
    fused = results[0]
    assert isinstance(fused, FusedHit)
    assert fused.hit.doc_id == "middleware-ordering"
    assert fused.entity_id == "section:middleware-ordering"
    # 1-hop neighborhood: the containing document, via the inbound has_section edge.
    assert len(fused.context) == 1
    context = fused.context[0]
    assert context.entity_id == "document:engineering handbook"
    assert context.entity_type == "document"
    assert context.predicate == "has_section"
    assert context.direction == "in"


def test_context_carries_graph_provenance_alongside_retrieval_score():
    fusion, _ = _fusion()
    fused = fusion.answer("deployment profile env override", k=1)[0]
    assert fused.hit.score > 0.0  # retrieval score preserved
    assert fused.hit.metadata["source_id"] == "handbook#deployment-profiles"
    assert fused.context[0].provenance is not None
    assert fused.context[0].provenance.source_id == "handbook#deployment-profiles"


def test_retrieval_order_is_preserved():
    fusion, retriever = _fusion()
    query = "offline pytest echo provider"
    fused_ids = [f.hit.doc_id for f in fusion.answer(query, k=3)]
    plain_ids = [h.doc_id for h in retriever.search(query, 3)]
    assert fused_ids == plain_ids
    assert fused_ids[0] == "testing-standards"


def test_mentions_neighbors_join_the_context():
    text = (
        "---\ntitle: Crossref\n---\n"
        "## Alpha Topic\nSee Beta Topic for the shared retention policy details.\n"
        "## Beta Topic\nRetention policy body.\n"
    )
    document = parse_markdown(text)
    retriever = HybridRetriever(InMemoryVectorIndex(), Bm25Index())
    index_corpus(retriever, document, source_id="xref")
    resolver = EntityResolver()
    graph = graph_from_docs(document, resolver, source_id="xref")
    fusion = GraphVectorFusion(retriever, graph, resolver)

    fused = fusion.answer("alpha topic shared retention", k=1)[0]
    assert fused.entity_id == "section:alpha-topic"
    by_predicate = {(c.predicate, c.direction): c for c in fused.context}
    assert ("has_section", "in") in by_predicate
    assert ("mentions", "out") in by_predicate
    assert by_predicate[("mentions", "out")].entity_id == "section:beta-topic"


def test_hit_without_graph_entity_keeps_empty_context():
    fusion, retriever = _fusion()
    # Indexed but never registered in the graph/resolver: fusion must not drop it.
    retriever.add("orphan", "orphan section about zebra telescopes", {"anchor": "orphan"})
    fused = fusion.answer("zebra telescopes", k=1)[0]
    assert fused.hit.doc_id == "orphan"
    assert fused.entity_id is None
    assert fused.context == ()
