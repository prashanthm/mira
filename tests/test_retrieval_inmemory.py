"""Tests for the in-memory retrieval reference implementations (ADR-021, ADR-028).

Covers :class:`HashEmbedder` determinism/normalization, cosine search ordering in
:class:`InMemoryVectorIndex`, and conformance to the retrieval Protocol seam.
"""

from __future__ import annotations

import math

import pytest

from mira.retrieval.inmemory import HashEmbedder, InMemoryVectorIndex, tokenize
from mira.retrieval.protocols import Embedder, SearchHit, VectorIndex
from mira.retrieval.sparse import Bm25Index


def test_hash_embedder_is_deterministic_across_instances():
    text = "middleware ordering chokepoint"
    assert HashEmbedder().embed(text) == HashEmbedder().embed(text)
    assert HashEmbedder(dimension=32).embed(text) == HashEmbedder(dimension=32).embed(text)


def test_hash_embedder_vectors_are_unit_normalized():
    vec = HashEmbedder(dimension=64).embed("auth correlation entitlement guardrail")
    assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, rel_tol=1e-9)


def test_hash_embedder_empty_text_is_zero_vector():
    vec = HashEmbedder(dimension=16).embed("   ")
    assert vec == (0.0,) * 16


def test_hash_embedder_rejects_non_positive_dimension():
    with pytest.raises(ValueError):
        HashEmbedder(dimension=0)


def test_tokenize_lowercases_and_splits_on_non_alphanumerics():
    assert tokenize("Guardrail-Out, ADR-009!") == ["guardrail", "out", "adr", "009"]


def test_protocol_conformance():
    assert isinstance(HashEmbedder(), Embedder)
    assert isinstance(InMemoryVectorIndex(), VectorIndex)
    # The sparse index deliberately shares the add/search surface (ADR-028).
    assert isinstance(Bm25Index(), VectorIndex)


def _index() -> InMemoryVectorIndex:
    index = InMemoryVectorIndex()
    index.add("auth", "auth entitlement guardrail middleware", {"source_id": "s#auth"})
    index.add("deploy", "deployment profile artifact env", {"source_id": "s#deploy"})
    index.add("tests", "pytest offline echo provider", {"source_id": "s#tests"})
    return index


def test_cosine_search_orders_by_similarity():
    hits = _index().search("auth guardrail middleware", 3)
    assert hits[0].doc_id == "auth"
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert all(isinstance(h, SearchHit) for h in hits)


def test_search_respects_k_and_carries_metadata():
    hits = _index().search("deployment profile", 1)
    assert len(hits) == 1
    assert hits[0].doc_id == "deploy"
    assert hits[0].metadata["source_id"] == "s#deploy"


def test_search_excludes_zero_similarity_documents():
    assert _index().search("qzxv", 3) == []


def test_search_with_non_positive_k_returns_nothing():
    assert _index().search("auth", 0) == []


def test_re_adding_a_doc_id_replaces_the_entry():
    index = _index()
    index.add("auth", "completely different words now", {"source_id": "s#auth2"})
    assert len(index) == 3
    hits = index.search("completely different words", 1)
    assert hits[0].doc_id == "auth"
    assert hits[0].metadata["source_id"] == "s#auth2"


def test_add_rejects_empty_doc_id():
    with pytest.raises(ValueError):
        _index().add("", "text", {})
