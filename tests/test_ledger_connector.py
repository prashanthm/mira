"""Tests for the ledger connector — the finance demo source (ADR-019, ADR-020).

Covers parse, ``SourceConnector`` conformance, typed MCP-tool exposure with
currency-bearing provenance, and a grounded end-to-end answer through the
federation fabric.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mira.connectors import SourceConnector, SourceRecord, export_tools
from mira.connectors.ledger import (
    LedgerConnector,
    LedgerParseError,
    from_file,
    from_text,
    parse_ledger,
)
from mira.fabric.federation import FederatedQueryResult, QueryRequest, query
from mira.tools.contract import ToolContract

FIXTURE = Path(__file__).parent / "fixtures" / "ledger.csv"


def _connector() -> LedgerConnector:
    return from_file(str(FIXTURE))


def test_parse_extracts_typed_entries():
    doc = parse_ledger(FIXTURE.read_text())
    assert len(doc.entries) == 7
    first = doc.entries[0]
    assert (first.date, first.account, first.category) == ("2026-02-11", "corp-card", "travel")
    assert first.amount == 412.50
    assert first.currency == "USD"
    assert doc.categories() == ("cloud", "tools", "travel")


def test_total_sums_category_within_period():
    doc = parse_ledger(FIXTURE.read_text())
    total, currency, count = doc.total("travel", "2026-03")
    assert total == pytest.approx(1336.40)
    assert currency == "USD"
    assert count == 2


def test_total_rejects_mixed_currencies():
    doc = parse_ledger(
        "date,account,category,amount,currency\n"
        "2026-03-01,a,travel,10.0,USD\n"
        "2026-03-02,a,travel,20.0,EUR\n"
    )
    with pytest.raises(LedgerParseError):
        doc.total("travel", "2026-03")


def test_parse_rejects_bad_header():
    with pytest.raises(LedgerParseError):
        parse_ledger("when,who,what,how-much,unit\n2026-01-01,a,b,1.0,USD\n")


def test_parse_rejects_ragged_row_and_bad_amount():
    with pytest.raises(LedgerParseError):
        parse_ledger("date,account,category,amount,currency\n2026-01-01,a,b,1.0\n")
    with pytest.raises(LedgerParseError):
        parse_ledger("date,account,category,amount,currency\n2026-01-01,a,b,ten,USD\n")


def test_connector_conforms_to_protocol():
    assert isinstance(_connector(), SourceConnector)


def test_describe_advertises_ledger_source_and_capabilities():
    desc = _connector().describe()
    assert desc.source_type == "ledger"
    assert set(desc.capabilities) == {"categories", "query"}


def test_query_returns_uniform_record_with_currency_provenance():
    record = _connector().query({"category": "travel", "period": "2026-03"})[0]
    assert isinstance(record, SourceRecord)
    assert record.provenance.source_type == "ledger"
    assert record.provenance.units == "USD"  # currency travels as provenance units
    assert record.payload["total"] == pytest.approx(1336.40)
    assert record.payload["currency"] == "USD"
    assert record.payload["entry_count"] == 2


@pytest.mark.parametrize("payload", [
    {"category": "travel", "period": "1999-01"},  # no entries in period
    {"category": "yachts", "period": "2026-03"},  # unknown category
    {"category": "travel"},                       # missing period
])
def test_query_rejects_bad_requests(payload):
    with pytest.raises(LedgerParseError):
        _connector().query(payload)


def test_connector_publishes_typed_read_only_mcp_tools():
    tools = {tool.name: tool for tool in export_tools(_connector())}
    assert set(tools) == {"ledger.categories", "ledger.query"}
    assert all(isinstance(tool, ToolContract) for tool in tools.values())
    assert tools["ledger.categories"].required_entitlement == "connector:ledger:categories"
    assert tools["ledger.query"].required_entitlement == "connector:ledger:query"
    assert all(tool.readOnlyHint and not tool.destructiveHint for tool in tools.values())
    schema = tools["ledger.query"].inputSchema
    assert schema["required"] == ["category", "period"]
    assert schema["properties"]["period"]["type"] == "string"


def test_grounded_query_through_federation_returns_attributed_answer():
    """Query the ledger in place via the fabric; the answer is denominated + attributed."""
    result = query(_connector(), QueryRequest(payload={"category": "cloud", "period": "2026-03"}))
    assert isinstance(result, FederatedQueryResult)
    assert result.attribution.connector_id == f"ledger:{FIXTURE}"
    assert result.attribution.source_name == str(FIXTURE)
    assert result.attribution.request_payload == {"category": "cloud", "period": "2026-03"}
    record = result.rows[0]  # grounded answer: total + currency, not a bare number
    assert record.payload["total"] == pytest.approx(3020.75)
    assert record.provenance.units == "USD"


def test_from_text_attributes_records_to_given_source_id():
    connector = from_text(FIXTURE.read_text(), source_id="ledger://corp/2026")
    record = connector.query({"category": "tools", "period": "2026-02"})[0]
    assert record.provenance.source_id == "ledger://corp/2026"
    assert connector.connector_id == "ledger:ledger://corp/2026"
