"""Tests for the entity + pluggable-aspect catalog (ADR-026)."""

from __future__ import annotations

import pytest

from mira.semantic.catalog import Catalog, CatalogEntry, CatalogError


def _catalog() -> Catalog:
    catalog = Catalog()
    catalog.register(
        CatalogEntry(
            entity_id="dataset:handbook",
            entity_type="dataset",
            aspects={"schema": {"sections": 3, "front_matter": ["title", "owner"]}},
        )
    )
    catalog.register(CatalogEntry(entity_id="dataset:ledger", entity_type="dataset"))
    catalog.register(CatalogEntry(entity_id="job:aggregate", entity_type="job"))
    return catalog


def test_register_and_get_round_trip():
    catalog = _catalog()
    entry = catalog.get("dataset:handbook")
    assert entry.entity_type == "dataset"
    assert entry.aspects["schema"]["sections"] == 3


def test_duplicate_registration_is_an_explicit_error():
    catalog = _catalog()
    with pytest.raises(CatalogError, match="already registered"):
        catalog.register(CatalogEntry(entity_id="dataset:handbook", entity_type="dataset"))


def test_attach_aspect_adds_metadata_without_touching_other_aspects():
    catalog = _catalog()
    updated = catalog.attach_aspect(
        "dataset:handbook",
        "provenance",
        {"source_type": "docs", "source_id": "tests/fixtures/handbook.md"},
    )
    assert updated.aspects["provenance"]["source_type"] == "docs"
    assert updated.aspects["schema"]["sections"] == 3  # prior aspect intact
    assert catalog.get("dataset:handbook") == updated


def test_attach_aspect_replaces_a_same_named_aspect():
    catalog = _catalog()
    catalog.attach_aspect("dataset:ledger", "quality", {"row_count": 7})
    catalog.attach_aspect("dataset:ledger", "quality", {"row_count": 8})
    assert catalog.get("dataset:ledger").aspects["quality"] == {"row_count": 8}


def test_find_filters_by_type_and_aspect():
    catalog = _catalog()
    catalog.attach_aspect("dataset:ledger", "lineage", {"job": "job:aggregate"})
    datasets = catalog.find(entity_type="dataset")
    assert [e.entity_id for e in datasets] == ["dataset:handbook", "dataset:ledger"]
    with_lineage = catalog.find(aspect="lineage")
    assert [e.entity_id for e in with_lineage] == ["dataset:ledger"]
    both = catalog.find(entity_type="dataset", aspect="schema")
    assert [e.entity_id for e in both] == ["dataset:handbook"]
    assert len(catalog.find()) == 3


def test_unknown_entity_and_bad_input_raise():
    catalog = _catalog()
    with pytest.raises(CatalogError):
        catalog.get("dataset:ghost")
    with pytest.raises(CatalogError):
        catalog.attach_aspect("dataset:ghost", "schema", {})
    with pytest.raises(CatalogError):
        catalog.attach_aspect("dataset:handbook", "", {})
    with pytest.raises(CatalogError):
        catalog.register(CatalogEntry(entity_id="", entity_type="dataset"))


def test_registered_entries_are_isolated_from_caller_mutation():
    catalog = Catalog()
    aspects = {"schema": {"cols": 5}}
    catalog.register(CatalogEntry(entity_id="d", entity_type="dataset", aspects=aspects))
    aspects["schema"]["cols"] = 99
    assert catalog.get("d").aspects["schema"]["cols"] == 5
