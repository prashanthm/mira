"""Provenance pass-through for federated results (ADR-019, ADR-037).

Federation returns connector-native rows (see :mod:`mira.fabric.federation`).
Once those rows cross into the agent runtime they must carry a tamper-evident
record of *where they came from* and a standing flag that the payload is
**untrusted** input — it has not passed the bidirectional guardrail pipeline
(ADR-037, inherited mcp-server ADR-021).

This module models that record (:class:`Provenance`), a result that carries it
(:class:`ProvenancedResult`), and helpers to ``attach`` provenance to a value
and ``preserve`` it across an arbitrary transform so the chain survives
end-to-end.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, TypeVar

T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True, slots=True)
class Provenance:
    """Origin record attached to a federated value.

    ``source_id`` and ``record_id`` identify the originating source and the
    specific record within it. ``units`` and ``crs`` (coordinate reference
    system) carry the physical interpretation the source asserts. ``untrusted``
    defaults to ``True``: source-derived data has not cleared the guardrail
    pipeline, so the safe default is to treat it as untrusted until a trusted
    boundary explicitly clears it.
    """

    source_id: str
    record_id: str
    units: str | None = None
    crs: str | None = None
    untrusted: bool = True


@dataclass(frozen=True, slots=True)
class ProvenancedResult:
    """A value paired with its :class:`Provenance` record."""

    value: Any
    provenance: Provenance


def attach(value: T, provenance: Provenance) -> ProvenancedResult:
    """Pair *value* with *provenance*, marking it untrusted by default.

    Source-derived data is untrusted unless the caller has explicitly built a
    cleared :class:`Provenance`; this is enforced here so the guardrail default
    cannot be skipped by simply calling :func:`attach`.
    """
    if not provenance.untrusted:
        return ProvenancedResult(value=value, provenance=provenance)
    return ProvenancedResult(value=value, provenance=replace(provenance, untrusted=True))


def preserve(result: ProvenancedResult, transform: Callable[[Any], U]) -> ProvenancedResult:
    """Apply *transform* to ``result.value``, carrying provenance through unchanged.

    The provenance record survives the transform verbatim — including the
    ``untrusted`` flag — because transforming source data does not launder it.
    """
    return ProvenancedResult(value=transform(result.value), provenance=result.provenance)


def mark_trusted(result: ProvenancedResult) -> ProvenancedResult:
    """Return *result* with provenance cleared as trusted.

    Only a trusted boundary (e.g. after the guardrail pipeline) should call
    this; it is the single explicit escape hatch from the untrusted default.
    """
    return ProvenancedResult(
        value=result.value,
        provenance=replace(result.provenance, untrusted=False),
    )
