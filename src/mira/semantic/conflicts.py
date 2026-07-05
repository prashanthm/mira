"""Measurement-vs-derived tagging and multi-source conflict surfacing (ADR-025).

Every claim about a canonical attribute carries a mandatory ``kind`` tag —
``measurement`` (a source observation as recorded) or ``derived`` (a computed or
interpreted value) — plus the provenance ``source_id`` it came from.
``surface_conflicts`` detects attributes where different sources return different
values and returns *all* disagreeing claims with their provenance: conflicts are
surfaced, never resolved. No latest-wins, no source-priority list, no fusion —
picking a winner is exactly what ADR-025 forbids the fabric to do silently.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

_VALID_KINDS = ("measurement", "derived")

ClaimKind = Literal["measurement", "derived"]


class ConflictModelError(ValueError):
    """Raised when a claim is malformed (unknown kind, missing provenance)."""


@dataclass(frozen=True, slots=True)
class Claim:
    """One attributed value: subject entity, attribute, value, kind tag, source."""

    subject: str
    attribute: str
    value: Any
    kind: ClaimKind
    source_id: str

    def __post_init__(self) -> None:
        if self.kind not in _VALID_KINDS:
            raise ConflictModelError(
                f"kind must be one of {_VALID_KINDS}, got {self.kind!r} (ADR-025)"
            )
        if not self.source_id:
            raise ConflictModelError("claims must carry provenance: source_id is required")


@dataclass(frozen=True, slots=True)
class Conflict:
    """Disagreeing claims for one (subject, attribute) — surfaced, never resolved."""

    subject: str
    attribute: str
    claims: tuple[Claim, ...]

    def values(self) -> tuple[Any, ...]:
        """The distinct disagreeing values, in claim order."""
        seen: list[Any] = []
        for claim in self.claims:
            if claim.value not in seen:
                seen.append(claim.value)
        return tuple(seen)


def surface_conflicts(claims: Iterable[Claim]) -> list[Conflict]:
    """Return one :class:`Conflict` per (subject, attribute) where sources disagree.

    A conflict exists when claims for the same subject and attribute carry
    differing values from at least two distinct sources. Same value from many
    sources is agreement, not conflict; differing values from a single source
    (e.g. a revision chain) are that source's own versioning, not a cross-source
    conflict. All claims of a conflicting attribute are returned — measurement
    and derived alike, each with its ``kind`` and provenance intact — so the
    consuming agent or user applies judgment; this function never picks a winner.
    """
    grouped: dict[tuple[str, str], list[Claim]] = {}
    for claim in claims:
        grouped.setdefault((claim.subject, claim.attribute), []).append(claim)

    conflicts: list[Conflict] = []
    for (subject, attribute), group in sorted(grouped.items()):
        distinct_values: list[Any] = []
        for claim in group:
            if claim.value not in distinct_values:
                distinct_values.append(claim.value)
        if len(distinct_values) < 2:
            continue
        disagreeing_sources = {c.source_id for c in group}
        if len(disagreeing_sources) < 2:
            continue
        conflicts.append(
            Conflict(subject=subject, attribute=attribute, claims=tuple(group))
        )
    return conflicts
