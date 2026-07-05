"""Aggregate-vs-federate decision policy (ADR-019).

Single decision point for the data fabric: given a *source* and a *data kind*,
:func:`decide` classifies a workload as ``"federate"`` (query-in-place at the
source) or ``"aggregate"`` (copy/index into a platform-managed store).

The rule follows ADR-019's data-class table:

- Operational / immovable / system-of-record sources (transactional warehouses,
  live event streams, ledgers, document stores, time-series historians) are
  federated in place.
- Analytical / RAG / session / eval data kinds (embeddings, RAG corpus, session
  and eval artifacts) are aggregated.
- Anything unrecognized defaults to ``"federate"`` — the conservative default
  that keeps data at the source and entitlements at their existing boundary.
"""

from __future__ import annotations

from typing import Literal

Decision = Literal["federate", "aggregate"]

FEDERATE: Decision = "federate"
AGGREGATE: Decision = "aggregate"

# Source-types whose data is operational, immovable, or system-of-record and is
# therefore queried in place (ADR-019 Rule 1). Compared case-insensitively.
_FEDERATE_SOURCES: frozenset[str] = frozenset(
    {
        "warehouse",
        "stream",
        "ledger",
        "docs",
        "timeseries",
    }
)

# Data-kinds that are analytical / RAG / session / eval workloads and are
# therefore selectively aggregated (ADR-019 Rule 2). Compared case-insensitively.
_AGGREGATE_DATA_KINDS: frozenset[str] = frozenset(
    {
        "embeddings",
        "embedding",
        "rag",
        "rag-corpus",
        "session",
        "eval",
        "eval-goldens",
        "goldens",
    }
)


def _normalize(value: str) -> str:
    return value.strip().lower()


def decide(source: str, data_kind: str) -> Decision:
    """Classify a ``(source, data_kind)`` pair as ``"federate"`` or ``"aggregate"``.

    Per ADR-019:

    1. Operational / immovable / system-of-record *sources* federate in place,
       regardless of data kind — entitlements and data gravity stay at source.
    2. Otherwise, analytical / RAG / session / eval *data kinds* aggregate.
    3. Otherwise, default to ``"federate"`` (the conservative ADR-019 default).

    Args:
        source: Source-system identifier (e.g. ``"warehouse"``, ``"ledger"``).
        data_kind: Workload data kind (e.g. ``"embeddings"``, ``"eval"``).

    Returns:
        ``"federate"`` or ``"aggregate"``.
    """
    normalized_source = _normalize(source)
    normalized_kind = _normalize(data_kind)

    # Rule 1 — immovable/operational sources federate regardless of data kind.
    if normalized_source in _FEDERATE_SOURCES:
        return FEDERATE

    # Rule 2 — analytical/RAG/session/eval data kinds aggregate.
    if normalized_kind in _AGGREGATE_DATA_KINDS:
        return AGGREGATE

    # Rule 3 — conservative default: keep data at the source.
    return FEDERATE
