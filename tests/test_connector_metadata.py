"""Tests for connector provenance + units/CRS metadata (e07-f03, ADR-020)."""

from __future__ import annotations

from mira.connectors.base import Provenance as ConnectorProvenance
from mira.connectors.base import SourceRecord
from mira.connectors.metadata import (
    UNKNOWN,
    attach_metadata,
    attach_record_metadata,
)
from mira.fabric.provenance import Provenance as FabricProvenance
from mira.fabric.provenance import ProvenancedResult


def test_attach_metadata_uses_the_fabric_shape():
    result = attach_metadata(
        {"depth": 1000.0, "gr": 45.2},
        source_id="docs-filesystem",
        record_id="well-a/log-0001",
        units="API",
        crs="EPSG:4326",
    )

    # Same shape the fabric consumes (e06-f04): ProvenancedResult wrapping a
    # fabric Provenance, not the connector-layer Provenance.
    assert isinstance(result, ProvenancedResult)
    assert isinstance(result.provenance, FabricProvenance)
    assert result.value == {"depth": 1000.0, "gr": 45.2}
    assert result.provenance.source_id == "docs-filesystem"
    assert result.provenance.record_id == "well-a/log-0001"
    assert result.provenance.units == "API"
    assert result.provenance.crs == "EPSG:4326"


def test_source_data_stays_untrusted():
    # attach_metadata does not launder source data: the fabric untrusted default holds.
    result = attach_metadata([1, 2, 3], source_id="s", record_id="r", units="m")
    assert result.provenance.untrusted is True


def test_missing_units_is_explicit_not_silently_absent():
    result = attach_metadata(
        {"x": 1},
        source_id="seismic",
        record_id="survey-7/trace-3",
        units=None,
        crs="EPSG:32633",
    )

    # The spine must be able to flag missing units, so it is an explicit sentinel
    # rather than None / silently absent.
    assert result.provenance.units == UNKNOWN
    assert result.provenance.units is not None
    assert result.provenance.crs == "EPSG:32633"


def test_missing_crs_is_explicit():
    result = attach_metadata({"x": 1}, source_id="s", record_id="r", units="m", crs=None)
    assert result.provenance.crs == UNKNOWN
    assert result.provenance.units == "m"


def test_both_units_and_crs_missing_are_explicit():
    # Defaults: no units/crs supplied at all.
    result = attach_metadata("rows", source_id="s", record_id="r")
    assert result.provenance.units == UNKNOWN
    assert result.provenance.crs == UNKNOWN


def test_blank_units_is_treated_as_missing():
    # Whitespace-only is not a meaningful unit; make it explicit.
    result = attach_metadata({"x": 1}, source_id="s", record_id="r", units="   ", crs="\t")
    assert result.provenance.units == UNKNOWN
    assert result.provenance.crs == UNKNOWN


def test_attach_record_metadata_bridges_connector_record_to_fabric_shape():
    record = SourceRecord(
        provenance=ConnectorProvenance(
            source_type="docs",
            source_id="docs-filesystem",
            units="API",
            crs="EPSG:4326",
        ),
        payload={"depth": 1000.0},
    )

    result = attach_record_metadata(record, record_id="well-a/log-0001")

    assert isinstance(result, ProvenancedResult)
    assert isinstance(result.provenance, FabricProvenance)
    assert result.value == {"depth": 1000.0}
    assert result.provenance.source_id == "docs-filesystem"
    assert result.provenance.record_id == "well-a/log-0001"
    assert result.provenance.units == "API"
    assert result.provenance.crs == "EPSG:4326"
    assert result.provenance.untrusted is True


def test_attach_record_metadata_makes_missing_units_explicit():
    record = SourceRecord(
        provenance=ConnectorProvenance(
            source_type="gis",
            source_id="gis-store",
            units=None,
            crs=None,
        ),
        payload={"geom": "POINT(0 0)"},
    )

    result = attach_record_metadata(record, record_id="layer-1/feature-9")

    assert result.provenance.units == UNKNOWN
    assert result.provenance.crs == UNKNOWN
