"""Tests for the skills registry (ADR-032): versioning, entitlement union, authorization."""

from __future__ import annotations

import pytest

from mira.tools.contract import ToolContract
from mira.tools.skills import (
    Skill,
    SkillsError,
    SkillsRegistry,
    SkillVersionExists,
    UnknownSkillError,
    UnresolvedToolError,
)

_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": True}


def _contract(name: str, entitlement: str) -> ToolContract:
    return ToolContract(
        name=name,
        description=f"test tool {name}",
        inputSchema=dict(_SCHEMA),
        required_entitlement=entitlement,
        readOnlyHint=True,
    )


CONTRACTS = {
    "ledger.query": _contract("ledger.query", "connector:ledger:query"),
    "ledger.categories": _contract("ledger.categories", "connector:ledger:categories"),
    "docs.search": _contract("docs.search", "connector:docs:search"),
}


def _skill(version: str = "1.0.0", tools: tuple[str, ...] = ("ledger.query",)) -> Skill:
    return Skill(
        name="spend-summary",
        version=version,
        description="Total a category's spend and summarize it",
        tool_names=tools,
    )


def test_register_aggregates_entitlement_union():
    registry = SkillsRegistry()
    stored = registry.register(
        _skill(tools=("ledger.query", "ledger.categories", "docs.search")), CONTRACTS
    )
    assert stored.required_entitlements == frozenset(
        {"connector:ledger:query", "connector:ledger:categories", "connector:docs:search"}
    )


def test_register_rejects_unresolved_tool_names():
    registry = SkillsRegistry()
    with pytest.raises(UnresolvedToolError, match="unknown tools"):
        registry.register(_skill(tools=("ledger.query", "missing.tool")), CONTRACTS)
    assert registry.skills() == ()


def test_register_requires_at_least_one_tool():
    registry = SkillsRegistry()
    with pytest.raises(SkillsError, match="at least one tool"):
        registry.register(_skill(tools=()), CONTRACTS)


def test_versions_are_immutable():
    registry = SkillsRegistry()
    registry.register(_skill("1.0.0"), CONTRACTS)
    with pytest.raises(SkillVersionExists, match="immutable"):
        registry.register(_skill("1.0.0"), CONTRACTS)


def test_resolve_named_and_highest_version():
    registry = SkillsRegistry()
    registry.register(_skill("1.9.0"), CONTRACTS)
    registry.register(_skill("1.10.0"), CONTRACTS)
    registry.register(_skill("1.2.0"), CONTRACTS)

    assert registry.resolve("spend-summary", "1.2.0").version == "1.2.0"
    # None → highest registered version (numeric tuple compare: 1.10 > 1.9).
    assert registry.resolve("spend-summary").version == "1.10.0"


def test_resolve_unknown_skill_or_version_raises():
    registry = SkillsRegistry()
    with pytest.raises(UnknownSkillError):
        registry.resolve("nope")
    registry.register(_skill("1.0.0"), CONTRACTS)
    with pytest.raises(UnknownSkillError, match="no version"):
        registry.resolve("spend-summary", "9.9.9")


def test_authorize_requires_all_entitlements_fail_closed():
    registry = SkillsRegistry()
    stored = registry.register(
        _skill(tools=("ledger.query", "docs.search")), CONTRACTS
    )

    assert registry.authorize(
        stored, {"connector:ledger:query", "connector:docs:search", "extra"}
    )
    # Partial grant → denied (fail-closed: ALL required entitlements needed).
    assert not registry.authorize(stored, {"connector:ledger:query"})
    assert not registry.authorize(stored, set())


def test_authorize_denies_unregistered_skill():
    registry = SkillsRegistry()
    ghost = _skill()
    assert not registry.authorize(ghost, {"connector:ledger:query"})


def test_skills_listing_is_ordered():
    registry = SkillsRegistry()
    registry.register(_skill("2.0.0"), CONTRACTS)
    registry.register(_skill("1.0.0"), CONTRACTS)
    other = Skill(
        name="a-doc-brief",
        version="1.0.0",
        description="Summarize a docs search",
        tool_names=("docs.search",),
    )
    registry.register(other, CONTRACTS)

    listed = [(s.name, s.version) for s in registry.skills()]
    assert listed == [
        ("a-doc-brief", "1.0.0"),
        ("spend-summary", "1.0.0"),
        ("spend-summary", "2.0.0"),
    ]
