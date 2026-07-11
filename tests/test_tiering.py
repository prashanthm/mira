"""Tests for model tiers, the difficulty heuristic, and TierPolicy (ADR-052)."""

from __future__ import annotations

import pytest

from mira.model.tiering import (
    TIER_ORDER,
    ModelTier,
    TierPolicy,
    classify_difficulty,
    next_tier_up,
)


def test_tier_order_and_next_tier_up():
    assert TIER_ORDER == ("light", "standard", "deep")
    assert next_tier_up("light") == "standard"
    assert next_tier_up("standard") == "deep"
    assert next_tier_up("deep") is None
    assert next_tier_up("unknown") is None
    assert next_tier_up("a", tiers=("a", "b")) == "b"


def test_explicit_tool_call_short_circuits_to_light():
    query = (
        "why should we compare and analyze everything about the entire architecture "
        ':tool:ledger.query:{"category": "cloud"} and then explain the trade-off? '
        "Also, how does it work? " + "word " * 50
    )
    assert classify_difficulty(query) == ModelTier.LIGHT


def test_short_plain_query_is_light():
    assert classify_difficulty("total travel spend") == ModelTier.LIGHT


def test_medium_length_query_is_standard():
    query = "please list the middleware ordering rules that the engineering handbook documents for services"
    assert len(query.split()) > 12
    assert classify_difficulty(query) == ModelTier.STANDARD


def test_analytic_multi_part_long_query_is_deep():
    query = (
        "Why did cloud spend increase last quarter? How does it compare to travel spend? "
        "Explain the trade-off and recommend a budget allocation for the next period "
        "so the team can plan accordingly with confidence and clear ownership."
    )
    assert classify_difficulty(query) == ModelTier.DEEP


def test_cross_domain_hits_add_weight():
    domains = {
        "research": frozenset({"handbook", "middleware"}),
        "finance": frozenset({"spend", "ledger"}),
    }
    query = "handbook middleware and ledger spend"
    without = classify_difficulty(query)
    with_domains = classify_difficulty(query, domain_keywords=domains)
    assert without == ModelTier.LIGHT
    assert with_domains == ModelTier.STANDARD  # +2 cross-domain on a 0-score query


def test_heuristic_is_deterministic():
    query = "Why compare spend? Explain the handbook and then the ledger; recommend."
    assert {classify_difficulty(query) for _ in range(5)} == {classify_difficulty(query)}


@pytest.mark.parametrize(
    "explicit,agent,expected",
    [
        ("deep", "research", "deep"),  # explicit beats hint
        (None, "research", "light"),  # agent hint beats heuristic
        (None, "unknown", "standard"),  # heuristic when no hint
    ],
)
def test_tier_policy_precedence(explicit, agent, expected):
    policy = TierPolicy(
        agent_tiers={"research": "light"},
        classifier=lambda prompt: "standard",
    )
    assert policy.resolve("q", agent=agent, explicit=explicit) == expected


def test_tier_policy_default_when_classifier_abstains():
    policy = TierPolicy(classifier=lambda prompt: "", default_tier="standard")
    assert policy.resolve("q", agent="x") == "standard"
    assert TierPolicy(classifier=lambda prompt: "").resolve("q", agent="x") is None
