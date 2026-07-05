"""Tests for federation query-in-place (ADR-019)."""

from dataclasses import dataclass, field
from typing import Any

from mira.fabric.federation import FederatedQueryResult, QueryRequest, query


@dataclass
class FakeConnector:
    """In-memory connector that returns a stable object reference."""

    connector_id: str = "docs-filesystem"
    source_name: str = "docs://handbook"
    _store: list[dict[str, Any]] = field(
        default_factory=lambda: [{"depth": 1000.0, "gr": 45.2}]
    )

    def query(self, request: QueryRequest) -> list[dict[str, Any]]:
        if request.payload.get("filter"):
            key, value = next(iter(request.payload["filter"].items()))
            return [row for row in self._store if row.get(key) == value]
        return self._store


class LocalDataStore:
    """Simulated persistence layer federation must not write to."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def ingest(self, rows: Any) -> None:
        if isinstance(rows, list):
            self.rows.extend(rows)
        else:
            self.rows.append(rows)


def test_query_dispatches_to_connector_and_returns_attributed_result():
    connector = FakeConnector()
    request = QueryRequest(payload={"filter": {"depth": 1000.0}})

    result = query(connector, request)

    assert isinstance(result, FederatedQueryResult)
    assert result.attribution.connector_id == "docs-filesystem"
    assert result.attribution.source_name == "docs://handbook"
    assert result.attribution.request_payload == {"filter": {"depth": 1000.0}}
    assert result.rows == [{"depth": 1000.0, "gr": 45.2}]


def test_query_does_not_copy_rows_to_local_store():
    connector = FakeConnector()
    store = LocalDataStore()
    source_rows = connector.query(QueryRequest(payload={}))

    result = query(connector, QueryRequest(payload={}))

    assert result.rows is source_rows
    store.ingest(result.rows)
    assert len(store.rows) == 1
    assert store.rows[0] is source_rows[0]


def test_query_never_writes_to_a_local_store():
    """Negative control: federation must not ingest into local persistence."""
    connector = FakeConnector()
    store = LocalDataStore()

    query(connector, QueryRequest(payload={"noop": True}))

    assert store.rows == []
