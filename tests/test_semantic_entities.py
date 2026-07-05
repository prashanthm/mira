"""Tests for deterministic-key-first canonical entity resolution (ADR-022)."""

from __future__ import annotations

import pytest

from mira.semantic.entities import CanonicalEntity, EntityResolutionError, EntityResolver


def test_resolve_creates_a_typed_canonical_node():
    resolver = EntityResolver()
    entity = resolver.resolve("account", ["corp-card"], attributes={"kind": "card"})
    assert entity.entity_type == "account"
    assert entity.entity_id == "account:corp-card"
    assert entity.keys == frozenset({"corp-card"})
    assert entity.attributes == {"kind": "card"}


def test_resolution_is_deterministic_and_idempotent():
    resolver = EntityResolver()
    first = resolver.resolve("account", ["corp-card"])
    second = resolver.resolve("account", ["Corp-Card "])  # normalization: case + whitespace
    assert first.entity_id == second.entity_id
    assert len(resolver.entities()) == 1


def test_new_keys_link_non_destructively_to_the_matched_node():
    resolver = EntityResolver()
    resolver.resolve("counterparty", ["lei-529900", "acme"])
    matched = resolver.resolve("counterparty", ["acme", "vendor-77"])
    assert matched.entity_id == "counterparty:acme"
    assert matched.keys == frozenset({"lei-529900", "acme", "vendor-77"})
    # The new key now resolves deterministically too.
    assert resolver.resolve("counterparty", ["vendor-77"]).entity_id == matched.entity_id


def test_same_key_under_different_types_stays_distinct():
    resolver = EntityResolver()
    account = resolver.resolve("account", ["travel"])
    category = resolver.resolve("category", ["travel"])
    assert account.entity_id != category.entity_id


def test_keys_matching_two_nodes_refuse_to_merge():
    resolver = EntityResolver()
    resolver.resolve("account", ["a1"])
    resolver.resolve("account", ["a2"])
    with pytest.raises(EntityResolutionError, match="refusing to merge"):
        resolver.resolve("account", ["a1", "a2"])


def test_link_alias_is_a_non_destructive_crosswalk():
    resolver = EntityResolver()
    entity = resolver.resolve("account", ["corp-card"])
    updated = resolver.link_alias(entity.entity_id, "AMEX-01")
    assert "amex-01" in updated.aliases
    assert "corp-card" in updated.keys  # nothing was overwritten
    assert resolver.resolve("account", ["amex-01"]).entity_id == entity.entity_id


def test_link_alias_conflict_is_an_explicit_error_never_a_remap():
    resolver = EntityResolver()
    resolver.resolve("account", ["a1"])
    other = resolver.resolve("account", ["a2"])
    with pytest.raises(EntityResolutionError, match="refusing to remap"):
        resolver.link_alias(other.entity_id, "a1")


def test_link_alias_rejects_unknown_entity_and_empty_alias():
    resolver = EntityResolver()
    entity = resolver.resolve("account", ["a1"])
    with pytest.raises(EntityResolutionError):
        resolver.link_alias("account:ghost", "x")
    with pytest.raises(EntityResolutionError):
        resolver.link_alias(entity.entity_id, "   ")


def test_resolve_rejects_empty_input():
    resolver = EntityResolver()
    with pytest.raises(EntityResolutionError):
        resolver.resolve("account", [])
    with pytest.raises(EntityResolutionError):
        resolver.resolve("   ", ["k"])


def test_lookup_is_non_creating():
    resolver = EntityResolver()
    assert resolver.lookup("account", ["ghost"]) is None
    assert resolver.entities() == ()
    created = resolver.resolve("account", ["real"])
    assert resolver.lookup("account", ["real"]) == created


def test_probabilistic_fallback_hook_runs_only_when_no_key_matches():
    calls: list[tuple[str, frozenset[str]]] = []

    def fallback(entity_type: str, keys: frozenset[str]) -> CanonicalEntity | None:
        calls.append((entity_type, keys))
        return None  # no probabilistic candidate proposed

    resolver = EntityResolver(fallback=fallback)
    resolver.resolve("counterparty", ["acme-corp"])  # no key match: fallback consulted
    resolver.resolve("counterparty", ["acme-corp"])  # deterministic hit: fallback skipped
    assert calls == [("counterparty", frozenset({"acme-corp"}))]


def test_probabilistic_fallback_can_link_an_unkeyed_record_to_an_existing_node():
    resolver_ref: list[EntityResolver] = []

    def fallback(entity_type: str, keys: frozenset[str]) -> CanonicalEntity | None:
        return resolver_ref[0].lookup("counterparty", ["acme-corp"])

    resolver = EntityResolver(fallback=fallback)
    resolver_ref.append(resolver)
    canonical = resolver.resolve("counterparty", ["acme-corp"])
    linked = resolver.resolve("counterparty", ["acme corporation ltd"])
    assert linked.entity_id == canonical.entity_id
    assert "acme corporation ltd" in linked.keys  # crosswalked, not merged away
