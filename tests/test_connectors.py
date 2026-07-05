"""Tests for the source connector framework (ADR-020)."""

from __future__ import annotations

from typing import Any

import pytest

from mira.connectors import (
    ConnectorRegistry,
    Provenance,
    SourceConnector,
    SourceDescription,
    SourceRecord,
    UnknownSourceTypeError,
    registry,
)


class FakeConnector:
    """Minimal in-memory connector conforming to the SourceConnector Protocol."""

    SOURCE_TYPE = "fake"

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_type=self.SOURCE_TYPE, capabilities=("query",)
        )

    def query(self, request: dict[str, Any]) -> list[SourceRecord]:
        return [
            SourceRecord(
                provenance=Provenance(
                    source_type=self.SOURCE_TYPE,
                    source_id=str(request.get("id", "0")),
                    units="m",
                    crs="EPSG:4326",
                ),
                payload={"echo": request},
            )
        ]


def test_fake_connector_conforms_to_protocol():
    conn = FakeConnector()
    assert isinstance(conn, SourceConnector)


def test_describe_returns_uniform_description():
    desc = FakeConnector().describe()
    assert isinstance(desc, SourceDescription)
    assert desc.source_type == "fake"
    assert "query" in desc.capabilities


def test_query_returns_uniform_records_with_provenance():
    records = FakeConnector().query({"id": "W-1"})
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SourceRecord)
    assert record.provenance.source_type == "fake"
    assert record.provenance.source_id == "W-1"
    assert record.provenance.units == "m"
    assert record.provenance.crs == "EPSG:4326"
    assert record.payload == {"echo": {"id": "W-1"}}


def test_registry_resolves_registered_source_type():
    reg = ConnectorRegistry()
    reg.register("fake", FakeConnector)
    conn = reg.resolve("fake")
    assert isinstance(conn, SourceConnector)
    assert conn.describe().source_type == "fake"


def test_registry_resolve_returns_fresh_instance_per_call():
    reg = ConnectorRegistry()
    reg.register("fake", FakeConnector)
    assert reg.resolve("fake") is not reg.resolve("fake")


def test_registry_lists_registered_source_types_sorted():
    reg = ConnectorRegistry()
    reg.register("ledger", FakeConnector)
    reg.register("docs", FakeConnector)
    assert reg.source_types() == ("docs", "ledger")


def test_registry_register_overrides_existing_factory():
    reg = ConnectorRegistry()
    reg.register("fake", FakeConnector)

    class OtherConnector(FakeConnector):
        SOURCE_TYPE = "fake-v2"

    reg.register("fake", OtherConnector)
    assert reg.resolve("fake").describe().source_type == "fake-v2"


def test_registry_rejects_empty_source_type():
    reg = ConnectorRegistry()
    with pytest.raises(ValueError):
        reg.register("", FakeConnector)


def test_unknown_source_type_raises():
    reg = ConnectorRegistry()
    with pytest.raises(UnknownSourceTypeError) as exc_info:
        reg.resolve("catalog")
    assert exc_info.value.source_type == "catalog"


def test_unknown_source_type_error_lists_known_types():
    reg = ConnectorRegistry()
    reg.register("fake", FakeConnector)
    with pytest.raises(UnknownSourceTypeError) as exc_info:
        reg.resolve("catalog")
    assert "fake" in str(exc_info.value)


def test_module_level_registry_is_a_connector_registry():
    assert isinstance(registry, ConnectorRegistry)
