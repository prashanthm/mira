"""Federation query-in-place layer (ADR-019).

Dispatches queries to source connectors and returns attributed results without
copying data into local persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SourceConnector(Protocol):
    """Minimal connector contract for federation dispatch.

    Interim stand-in until the e07-f01-t01 connector framework (#72) lands;
    intended to be aligned with / replaced by that interface.
    """

    connector_id: str
    source_name: str

    def query(self, request: QueryRequest) -> Any: ...


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Opaque query payload forwarded to a source connector.

    ``payload`` is treated as an immutable, opaque contract: federation copies
    it shallowly into :class:`SourceAttribution`, so callers must not mutate
    nested values after issuing a request.
    """

    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceAttribution:
    """Provenance record for a federated query result."""

    connector_id: str
    source_name: str
    request_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FederatedQueryResult:
    """Connector-native rows with source attribution; no local copy."""

    rows: Any
    attribution: SourceAttribution


def query(connector: SourceConnector, request: QueryRequest) -> FederatedQueryResult:
    """Dispatch *request* to *connector* and return an attributed, non-copied result."""
    rows = connector.query(request)
    return FederatedQueryResult(
        rows=rows,
        attribution=SourceAttribution(
            connector_id=connector.connector_id,
            source_name=connector.source_name,
            # Shallow copy: payload is an opaque, immutable contract (see
            # QueryRequest); nested values are intentionally shared by reference.
            request_payload=dict(request.payload),
        ),
    )
