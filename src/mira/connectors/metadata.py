"""Attach connector provenance + units/CRS metadata in the fabric's shape (ADR-020).

A :class:`~mira.connectors.base.SourceConnector` returns
:class:`~mira.connectors.base.SourceRecord` values. Before those records cross into
the agent runtime / fabric they must carry the *same* provenance shape the fabric
consumes (:class:`mira.fabric.provenance.Provenance` /
:class:`~mira.fabric.provenance.ProvenancedResult`, e06-f04) so the semantic spine can
reconcile heterogeneous sources and grounding can attribute (ADR-020, inherited
mcp-server ADR-021).

The fabric ``Provenance`` carries ``units``/``crs`` as ``str | None``, where ``None``
is ambiguous: it cannot be distinguished from "the source simply didn't set this
attribute". e07-f03 requires missing units/CRS to be represented **explicitly** so the
spine can *flag* it rather than silently treat it as absent. This module bridges that
gap: ``None`` units/CRS are normalised to the :data:`UNKNOWN` sentinel string so the
absence is a value the spine can see, not a hole. Source data stays untrusted (the
fabric default) — nothing here clears that flag.
"""

from __future__ import annotations

from typing import Any

from mira.connectors.base import SourceRecord
from mira.fabric.provenance import Provenance, ProvenancedResult, attach

# Explicit sentinel for units/CRS the source did not assert. Distinct from ``None``
# (ambiguous / "not set") so the semantic spine can flag the absence rather than
# silently treat the value as missing (e07-f03; ADR-020, inherited mcp-server ADR-021).
UNKNOWN = "unknown"


def _explicit(value: str | None) -> str:
    """Normalise a units/CRS value, making a missing one explicit.

    ``None`` and blank/whitespace-only strings become :data:`UNKNOWN` so downstream
    consumers never see a silently-absent unit or CRS; any other value is returned
    stripped of surrounding whitespace.
    """
    if value is None:
        return UNKNOWN
    stripped = value.strip()
    return stripped if stripped else UNKNOWN


def attach_metadata(
    result: Any,
    source_id: str,
    record_id: str,
    units: str | None = None,
    crs: str | None = None,
) -> ProvenancedResult:
    """Pair ``result`` with fabric-shaped provenance, making missing units/CRS explicit.

    Builds a :class:`mira.fabric.provenance.Provenance` from ``source_id``/``record_id``
    plus ``units``/``crs``, normalising missing units/CRS to the explicit
    :data:`UNKNOWN` sentinel (e07-f03). The value is returned via
    :func:`mira.fabric.provenance.attach`, so it rides in the same
    :class:`~mira.fabric.provenance.ProvenancedResult` shape the fabric consumes and
    inherits the untrusted default — source data is not laundered here.
    """
    provenance = Provenance(
        source_id=source_id,
        record_id=record_id,
        units=_explicit(units),
        crs=_explicit(crs),
    )
    return attach(result, provenance)


def attach_record_metadata(record: SourceRecord, record_id: str) -> ProvenancedResult:
    """Attach fabric-shaped provenance to a connector :class:`SourceRecord`.

    Bridges the connector record shape (which keys provenance by ``source_type`` +
    ``source_id``) to the fabric shape (``source_id`` + ``record_id``): the record's
    ``source_id`` and units/CRS are carried over, ``record_id`` identifies the specific
    record within the source, and the record's ``payload`` becomes the provenanced
    value. Missing units/CRS on the connector record are made explicit, the same as
    :func:`attach_metadata`.
    """
    return attach_metadata(
        record.payload,
        source_id=record.provenance.source_id,
        record_id=record_id,
        units=record.provenance.units,
        crs=record.provenance.crs,
    )
