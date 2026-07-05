"""Tests for the docs connector — the research demo source (ADR-019, ADR-020).

Covers parse, ``SourceConnector`` conformance, typed MCP-tool exposure with
anchor-bearing provenance, and a grounded end-to-end answer through the
federation fabric.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.connectors import SourceConnector, SourceRecord, export_tools
from mira.connectors.docs import DocsConnector, DocsParseError, from_file, from_text, parse_markdown
from mira.fabric.federation import FederatedQueryResult, QueryRequest, query
from mira.tools.contract import ToolContract

FIXTURE = Path(__file__).parent / "fixtures" / "handbook.md"


def _connector() -> DocsConnector:
    return from_file(str(FIXTURE))


def test_parse_extracts_headers_and_sections():
    doc = parse_markdown(FIXTURE.read_text())
    assert doc.headers["title"] == "Engineering Handbook"
    assert doc.headers["owner"] == "platform"
    assert [s.anchor for s in doc.sections] == [
        "middleware-ordering",
        "deployment-profiles",
        "testing-standards",
    ]
    assert doc.section("middleware-ordering").title == "Middleware Ordering"
    assert "guardrail-out" in doc.section("middleware-ordering").body


def test_parse_rejects_unterminated_front_matter():
    with pytest.raises(DocsParseError):
        parse_markdown("---\ntitle: Broken\n\n## Section\nbody\n")


def test_parse_rejects_document_without_sections():
    with pytest.raises(DocsParseError):
        parse_markdown("# Title only\n\nprose without any level-two headings\n")


def test_connector_conforms_to_protocol():
    assert isinstance(_connector(), SourceConnector)


def test_describe_advertises_docs_source_and_capabilities():
    desc = _connector().describe()
    assert desc.source_type == "docs"
    assert set(desc.capabilities) == {"sections", "search"}


def test_query_returns_uniform_record_with_anchor_provenance():
    record = _connector().query({"query": "middleware"})[0]
    assert isinstance(record, SourceRecord)
    assert record.provenance.source_type == "docs"
    assert record.provenance.source_id.endswith("#middleware-ordering")  # citable anchor
    assert record.payload["anchor"] == "middleware-ordering"
    assert record.payload["title"] == "Middleware Ordering"
    assert "guardrail-in" in record.payload["snippet"]
    assert record.payload["doc_title"] == "Engineering Handbook"


@pytest.mark.parametrize("payload", [
    {"query": "no-such-topic-anywhere"},  # no matching section
    {},                                   # missing query
])
def test_query_rejects_bad_requests(payload):
    with pytest.raises(DocsParseError):
        _connector().query(payload)


def test_connector_publishes_typed_read_only_mcp_tools():
    tools = {tool.name: tool for tool in export_tools(_connector())}
    assert set(tools) == {"docs.sections", "docs.search"}
    assert all(isinstance(tool, ToolContract) for tool in tools.values())
    assert tools["docs.sections"].required_entitlement == "connector:docs:sections"
    assert tools["docs.search"].required_entitlement == "connector:docs:search"
    assert all(tool.readOnlyHint and not tool.destructiveHint for tool in tools.values())
    schema = tools["docs.search"].inputSchema
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["type"] == "string"


def test_grounded_query_through_federation_returns_attributed_answer():
    """Query the corpus in place via the fabric; the answer is attributed to a section."""
    result = query(_connector(), QueryRequest(payload={"query": "profiles"}))
    assert isinstance(result, FederatedQueryResult)
    assert result.attribution.connector_id == f"docs:{FIXTURE}"
    assert result.attribution.source_name == str(FIXTURE)
    assert result.attribution.request_payload == {"query": "profiles"}
    record = result.rows[0]  # grounded answer: snippet + anchor, not bare prose
    assert record.payload["anchor"] == "deployment-profiles"
    assert record.provenance.source_id.endswith("#deployment-profiles")


def test_from_text_attributes_records_to_given_source_id():
    connector = from_text(FIXTURE.read_text(), source_id="docs://handbook")
    record = connector.query({"query": "testing"})[0]
    assert record.provenance.source_id == "docs://handbook#testing-standards"
    assert connector.connector_id == "docs:docs://handbook"
