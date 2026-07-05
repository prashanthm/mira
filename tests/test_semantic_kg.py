"""Tests for the in-memory knowledge-graph spine and its builders (ADR-027)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.connectors.base import Provenance
from mira.connectors.docs import parse_markdown
from mira.connectors.ledger import parse_ledger
from mira.semantic.entities import EntityResolver
from mira.semantic.kg import KnowledgeGraph, KnowledgeGraphError, graph_from_docs, graph_from_ledger

FIXTURES = Path(__file__).parent / "fixtures"


def _small_graph() -> tuple[KnowledgeGraph, EntityResolver]:
    resolver = EntityResolver()
    graph = KnowledgeGraph()
    doc = resolver.resolve("document", ["handbook"])
    sec_a = resolver.resolve("section", ["alpha"])
    sec_b = resolver.resolve("section", ["beta"])
    for node in (doc, sec_a, sec_b):
        graph.add_node(node)
    graph.add_edge(doc.entity_id, "has_section", sec_a.entity_id)
    graph.add_edge(doc.entity_id, "has_section", sec_b.entity_id)
    graph.add_edge(
        sec_a.entity_id,
        "mentions",
        sec_b.entity_id,
        Provenance(source_type="docs", source_id="handbook#alpha"),
    )
    return graph, resolver


def test_add_edge_requires_known_nodes_and_predicate():
    graph, resolver = _small_graph()
    with pytest.raises(KnowledgeGraphError, match="unknown node"):
        graph.add_edge("document:handbook", "has_section", "section:ghost")
    with pytest.raises(KnowledgeGraphError, match="predicate"):
        graph.add_edge("document:handbook", "  ", "section:alpha")


def test_neighbors_cover_both_directions_and_filter_by_predicate():
    graph, _ = _small_graph()
    edges = graph.neighbors("section:alpha")
    assert {(e.subject_id, e.predicate, e.object_id) for e in edges} == {
        ("document:handbook", "has_section", "section:alpha"),
        ("section:alpha", "mentions", "section:beta"),
    }
    mentions = graph.neighbors("section:alpha", predicate="mentions")
    assert len(mentions) == 1
    assert mentions[0].provenance == Provenance(source_type="docs", source_id="handbook#alpha")
    with pytest.raises(KnowledgeGraphError):
        graph.neighbors("section:ghost")


def test_duplicate_edges_are_not_double_stored():
    graph, _ = _small_graph()
    before = len(graph.edges())
    graph.add_edge("document:handbook", "has_section", "section:alpha")
    assert len(graph.edges()) == before


def test_subgraph_bounds_traversal_by_depth():
    graph, _ = _small_graph()
    zero = graph.subgraph("document:handbook", 0)
    assert len(zero) == 1 and zero.edges() == ()
    one = graph.subgraph("section:beta", 1)
    # beta reaches the document (has_section, inbound) and alpha (mentions, inbound).
    assert len(one) == 3
    assert len(one.edges()) == 3
    with pytest.raises(KnowledgeGraphError):
        graph.subgraph("document:handbook", -1)


def test_graph_from_ledger_builds_account_category_entry_spine():
    document = parse_ledger((FIXTURES / "ledger.csv").read_text())
    resolver = EntityResolver()
    graph = graph_from_ledger(document, resolver, source_id="demo-ledger")

    assert graph.has_node("account:corp-card")
    assert graph.has_node("account:ap")
    for category in ("travel", "tools", "cloud"):
        assert graph.has_node(f"category:{category}")
    # 7 entries, each with a posted_to and an in_category edge.
    assert len(graph) == 2 + 3 + 7
    assert len(graph.edges()) == 14

    posted = graph.neighbors("account:corp-card", predicate="posted_to")
    assert len(posted) == 5
    assert all(e.provenance.source_id == "demo-ledger" for e in posted)
    assert all(e.provenance.units == "USD" for e in posted)

    entry = graph.node("entry:demo-ledger:0")
    assert entry.attributes["date"] == "2026-02-11"
    assert entry.attributes["amount"] == 412.50


def test_graph_from_docs_builds_document_section_spine():
    document = parse_markdown((FIXTURES / "handbook.md").read_text())
    resolver = EntityResolver()
    graph = graph_from_docs(document, resolver, source_id="handbook")

    doc_id = "document:engineering handbook"
    assert graph.has_node(doc_id)
    sections = graph.neighbors(doc_id, predicate="has_section")
    assert {e.object_id for e in sections} == {
        "section:middleware-ordering",
        "section:deployment-profiles",
        "section:testing-standards",
    }
    assert all(e.provenance.source_type == "docs" for e in sections)
    assert any(e.provenance.source_id == "handbook#middleware-ordering" for e in sections)
    # The handbook has no cross-references between section bodies.
    assert not [e for e in graph.edges() if e.predicate == "mentions"]


def test_graph_from_docs_adds_mentions_edges_for_cross_references():
    text = (
        "---\ntitle: Crossref\n---\n"
        "## Alpha Topic\nSee Beta Topic for details.\n"
        "## Beta Topic\nStandalone body.\n"
    )
    graph = graph_from_docs(parse_markdown(text), EntityResolver(), source_id="xref")
    mentions = [e for e in graph.edges() if e.predicate == "mentions"]
    assert len(mentions) == 1
    assert mentions[0].subject_id == "section:alpha-topic"
    assert mentions[0].object_id == "section:beta-topic"
    assert mentions[0].provenance.source_id == "xref#alpha-topic"
