"""Model tiers, deterministic difficulty classification, and tier policy (ADR-052).

Tiers name capability classes (``light`` → ``deep``), not concrete models —
the tier→model mapping is deployment configuration (``MODEL_ROUTES``).
:func:`classify_difficulty` is pure and structural so the offline test/eval
paths stay deterministic: identical input, identical tier, no model call.

Terminology fence (ADR-039 vs ADR-052): "escalation" unqualified means HITL;
everything here is *model-tier* selection and escalation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum


class ModelTier(str, Enum):
    """Capability classes a route can declare and an agent can request."""

    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


TIER_ORDER: tuple[str, ...] = (ModelTier.LIGHT, ModelTier.STANDARD, ModelTier.DEEP)


def next_tier_up(tier: str, *, tiers: tuple[str, ...] = TIER_ORDER) -> str | None:
    """The next stronger tier in the ladder, or None at (or beyond) the top."""
    try:
        index = tiers.index(tier)
    except ValueError:
        return None
    return tiers[index + 1] if index + 1 < len(tiers) else None


# --- Deterministic difficulty heuristic ------------------------------------
# Same word tokenization idiom as the agent-card keyword matcher.
_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.]*")

# The explicit-tool-call marker the specialist scaffold parses; a query that
# names its tool call needs no reasoning-grade model.
_EXPLICIT_TOOL_MARKER = ":tool:"

_ANALYTIC_MARKERS = frozenset(
    {
        "why",
        "how",
        "compare",
        "versus",
        "vs",
        "explain",
        "analyze",
        "analyse",
        "trade-off",
        "tradeoff",
        "recommend",
    }
)

_ENUMERATION = re.compile(r";|\b\d+\.\s|\band then\b", re.IGNORECASE)

# Scoring table constants (pinned by tests).
SHORT_QUERY_WORDS = 12
LONG_QUERY_WORDS = 40
STANDARD_THRESHOLD = 1  # score >= this -> standard
DEEP_THRESHOLD = 3  # score >= this -> deep


def classify_difficulty(
    query: str,
    *,
    domain_keywords: Mapping[str, frozenset[str]] | None = None,
) -> str:
    """Structurally classify a query into a tier — pure and deterministic.

    Additive score: length (0/+1/+2), multi-part shape (+1), analytic markers
    (+1), keyword hits in two or more distinct domains (+2). An explicit
    ``:tool:`` call short-circuits to ``light`` regardless of anything else.
    """
    text = query or ""
    if _EXPLICIT_TOOL_MARKER in text:
        return ModelTier.LIGHT

    words = text.split()
    score = 0
    if len(words) > LONG_QUERY_WORDS:
        score += 2
    elif len(words) > SHORT_QUERY_WORDS:
        score += 1

    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if text.count("?") >= 2 or len(sentences) >= 2 or _ENUMERATION.search(text):
        score += 1

    tokens = set(_WORD.findall(text.lower()))
    if tokens & _ANALYTIC_MARKERS:
        score += 1

    if domain_keywords:
        hits = sum(1 for keywords in domain_keywords.values() if tokens & set(keywords))
        if hits >= 2:
            score += 2

    if score >= DEEP_THRESHOLD:
        return ModelTier.DEEP
    if score >= STANDARD_THRESHOLD:
        return ModelTier.STANDARD
    return ModelTier.LIGHT


@dataclass
class TierPolicy:
    """Resolve the tier for one call: explicit > agent hint > heuristic > default.

    ``agent_tiers`` maps agent names (card names) to tier names; ``classifier``
    is the question-difficulty fallback for agents without a hint. Every value
    is a plain string so operators can define custom ladders beyond
    :data:`TIER_ORDER`.
    """

    agent_tiers: Mapping[str, str] = field(default_factory=dict)
    classifier: Callable[[str], str] = classify_difficulty
    default_tier: str | None = None

    def resolve(
        self,
        prompt: str,
        *,
        agent: str = "default",
        explicit: str | None = None,
    ) -> str | None:
        if explicit:
            return explicit
        hint = self.agent_tiers.get(agent, "")
        if hint:
            return hint
        classified = self.classifier(prompt)
        if classified:
            return classified
        return self.default_tier


__all__ = [
    "DEEP_THRESHOLD",
    "LONG_QUERY_WORDS",
    "SHORT_QUERY_WORDS",
    "STANDARD_THRESHOLD",
    "TIER_ORDER",
    "ModelTier",
    "TierPolicy",
    "classify_difficulty",
    "next_tier_up",
]
