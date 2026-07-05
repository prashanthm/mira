"""Data fabric — federation and query-in-place (ADR-019)."""

from mira.fabric.federation import (
    FederatedQueryResult,
    QueryRequest,
    SourceAttribution,
    query,
)
from mira.fabric.provenance import (
    Provenance,
    ProvenancedResult,
    attach,
    mark_trusted,
    preserve,
)

__all__ = [
    "FederatedQueryResult",
    "Provenance",
    "ProvenancedResult",
    "QueryRequest",
    "SourceAttribution",
    "attach",
    "mark_trusted",
    "preserve",
    "query",
]
