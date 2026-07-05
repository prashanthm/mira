"""Tests for connector → typed MCP tool publication (ADR-020, ADR-031)."""

from __future__ import annotations

from typing import Any

import pytest

from mira.connectors import (
    Provenance,
    SourceDescription,
    SourceRecord,
    ToolSpec,
    export_tools,
)
from mira.tools.contract import MissingEntitlementError, ToolContract


class FakeConnector:
    """Plain SourceConnector: advertises capabilities, declares no tool specs."""

    SOURCE_TYPE = "fake"

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_type=self.SOURCE_TYPE, capabilities=("query", "stat")
        )

    def query(self, request: dict[str, Any]) -> list[SourceRecord]:
        return [
            SourceRecord(
                provenance=Provenance(source_type=self.SOURCE_TYPE, source_id="0"),
                payload={"echo": request},
            )
        ]


class RichConnector:
    """Connector that declares per-operation tool specs (ToolSpecConnector)."""

    SOURCE_TYPE = "catalog"

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_type=self.SOURCE_TYPE, capabilities=("search", "fetch")
        )

    def query(self, request: dict[str, Any]) -> list[SourceRecord]:
        return []

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                capability="search",
                required_entitlement="catalog:search",
                description="Search the catalog",
                input_schema={
                    "type": "object",
                    "properties": {"kind": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
            ToolSpec(
                capability="fetch",
                required_entitlement="catalog:fetch",
                idempotent=True,
            ),
        ]


def test_each_capability_published_as_a_tool():
    tools = export_tools(FakeConnector())
    assert {tool.name for tool in tools} == {"fake.query", "fake.stat"}


def test_published_tools_are_typed_tool_contracts():
    tools = export_tools(FakeConnector())
    assert tools  # non-empty
    assert all(isinstance(tool, ToolContract) for tool in tools)
    # Typed contract present: every tool carries a flat inputSchema.
    assert all(tool.inputSchema.get("type") == "object" for tool in tools)


def test_every_tool_declares_an_entitlement():
    tools = export_tools(FakeConnector())
    # Fail-closed: no exposed tool may have a blank entitlement.
    assert all(tool.required_entitlement.strip() for tool in tools)
    assert {tool.required_entitlement for tool in tools} == {
        "connector:fake:query",
        "connector:fake:stat",
    }


def test_default_tools_are_read_only_annotated():
    tools = export_tools(FakeConnector())
    # Connector queries are reads — annotations advertise non-destructive behaviour.
    assert all(tool.readOnlyHint for tool in tools)
    assert all(not tool.destructiveHint for tool in tools)


def test_rich_connector_specs_drive_publication():
    tools = {tool.name: tool for tool in export_tools(RichConnector())}
    assert set(tools) == {"catalog.search", "catalog.fetch"}

    search = tools["catalog.search"]
    assert search.required_entitlement == "catalog:search"
    assert search.description == "Search the catalog"
    assert search.inputSchema["properties"] == {"kind": {"type": "string"}}

    fetch = tools["catalog.fetch"]
    assert fetch.required_entitlement == "catalog:fetch"
    assert fetch.idempotent is True


def test_blank_entitlement_spec_is_rejected_fail_closed():
    """A spec that omits its entitlement must not yield a silently-exposed tool."""

    class BadConnector:
        def describe(self) -> SourceDescription:
            return SourceDescription(source_type="bad", capabilities=("op",))

        def query(self, request: dict[str, Any]) -> list[SourceRecord]:
            return []

        def tool_specs(self) -> list[ToolSpec]:
            return [ToolSpec(capability="op", required_entitlement="  ")]

    with pytest.raises(MissingEntitlementError):
        export_tools(BadConnector())


def test_connector_with_no_capabilities_publishes_no_tools():
    class EmptyConnector:
        def describe(self) -> SourceDescription:
            return SourceDescription(source_type="empty", capabilities=())

        def query(self, request: dict[str, Any]) -> list[SourceRecord]:
            return []

    assert export_tools(EmptyConnector()) == []
