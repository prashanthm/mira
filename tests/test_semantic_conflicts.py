"""Tests for measurement/derived tagging and conflict surfacing (ADR-025)."""

from __future__ import annotations

import pytest

from mira.semantic.conflicts import Claim, ConflictModelError, surface_conflicts


def test_differing_values_from_different_sources_surface_a_conflict():
    claims = [
        Claim("account:corp-card", "2026-03-travel", 1336.40, "derived", "ledger-a"),
        Claim("account:corp-card", "2026-03-travel", 1290.00, "derived", "ledger-b"),
    ]
    conflicts = surface_conflicts(claims)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.subject == "account:corp-card"
    assert conflict.attribute == "2026-03-travel"
    # Both claims come back with their provenance — nothing is resolved or dropped.
    assert {c.source_id for c in conflict.claims} == {"ledger-a", "ledger-b"}
    assert conflict.values() == (1336.40, 1290.00)


def test_same_value_from_multiple_sources_is_agreement_not_conflict():
    claims = [
        Claim("section:policy", "retention", "90 days", "measurement", "docs-a"),
        Claim("section:policy", "retention", "90 days", "measurement", "docs-b"),
    ]
    assert surface_conflicts(claims) == []


def test_differing_values_from_one_source_are_not_a_cross_source_conflict():
    claims = [
        Claim("account:ap", "balance", 100.0, "measurement", "ledger-a"),
        Claim("account:ap", "balance", 120.0, "measurement", "ledger-a"),
    ]
    assert surface_conflicts(claims) == []


def test_measurement_and_derived_kinds_are_preserved_in_the_conflict():
    claims = [
        Claim("account:ap", "q1-cloud", 3020.75, "measurement", "ledger"),
        Claim("account:ap", "q1-cloud", 3000.00, "derived", "forecast-model"),
    ]
    conflict = surface_conflicts(claims)[0]
    kinds = {(c.kind, c.source_id) for c in conflict.claims}
    assert kinds == {("measurement", "ledger"), ("derived", "forecast-model")}


def test_conflicts_are_grouped_per_subject_attribute_pair():
    claims = [
        Claim("a", "x", 1, "measurement", "s1"),
        Claim("a", "x", 2, "measurement", "s2"),
        Claim("a", "y", 1, "measurement", "s1"),  # different attribute, no conflict
        Claim("b", "x", 1, "measurement", "s1"),
        Claim("b", "x", 3, "derived", "s2"),
    ]
    conflicts = surface_conflicts(claims)
    assert [(c.subject, c.attribute) for c in conflicts] == [("a", "x"), ("b", "x")]


def test_no_winner_is_ever_picked():
    claims = [
        Claim("a", "x", 1, "measurement", "s1"),
        Claim("a", "x", 2, "measurement", "s2"),
        Claim("a", "x", 3, "measurement", "s3"),
    ]
    conflict = surface_conflicts(claims)[0]
    assert len(conflict.claims) == 3  # every disagreeing claim is returned
    assert conflict.values() == (1, 2, 3)


def test_claim_requires_a_valid_kind_and_provenance():
    with pytest.raises(ConflictModelError, match="kind"):
        Claim("a", "x", 1, "estimate", "s1")  # type: ignore[arg-type]
    with pytest.raises(ConflictModelError, match="source_id"):
        Claim("a", "x", 1, "measurement", "")


def test_empty_input_yields_no_conflicts():
    assert surface_conflicts([]) == []
