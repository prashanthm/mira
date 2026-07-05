"""Tests for the dependency-free BM25 lexical index (ADR-028)."""

from __future__ import annotations

import pytest

from mira.retrieval.sparse import Bm25Index


def _index() -> Bm25Index:
    index = Bm25Index()
    index.add("auth", "auth entitlement guardrail common", {"source_id": "s#auth"})
    index.add("deploy", "deployment profile artifact common", {"source_id": "s#deploy"})
    index.add("tests", "pytest offline echo rare common", {"source_id": "s#tests"})
    return index


def test_exact_term_match_ranks_first():
    hits = _index().search("guardrail entitlement", 3)
    assert hits[0].doc_id == "auth"
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_rare_term_outweighs_common_term():
    # "rare" appears in one doc, "common" in all three: idf must dominate.
    hits = _index().search("rare common", 3)
    assert hits[0].doc_id == "tests"


def test_only_matching_documents_are_scored():
    hits = _index().search("guardrail", 3)
    assert [h.doc_id for h in hits] == ["auth"]


def test_out_of_vocabulary_query_returns_nothing():
    assert _index().search("qzxv wibble", 3) == []


def test_empty_query_returns_nothing():
    assert _index().search("   ", 3) == []


def test_document_frequency_and_idf():
    index = _index()
    assert index.document_frequency("common") == 3
    assert index.document_frequency("rare") == 1
    assert index.document_frequency("qzxv") == 0
    assert index.idf("rare") > index.idf("common") > 0
    assert index.idf("qzxv") > index.idf("rare")


def test_k_limits_results_and_metadata_travels():
    hits = _index().search("common", 2)
    assert len(hits) == 2
    assert all("source_id" in h.metadata for h in hits)


def test_length_normalization_prefers_shorter_doc_at_equal_tf():
    index = Bm25Index()
    index.add("short", "target term", {})
    index.add("long", "target term padded with many extra unrelated words here", {})
    hits = index.search("target", 2)
    assert hits[0].doc_id == "short"


def test_re_adding_a_doc_id_replaces_the_entry():
    index = _index()
    index.add("auth", "different vocabulary entirely", {})
    assert len(index) == 3
    assert index.document_frequency("guardrail") == 0


def test_invalid_params_are_rejected():
    with pytest.raises(ValueError):
        Bm25Index(k1=-1.0)
    with pytest.raises(ValueError):
        Bm25Index(b=1.5)
    with pytest.raises(ValueError):
        _index().add("", "text", {})
