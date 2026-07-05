"""Role-based storage behind Protocols (ADR-021).

Four storage roles for the selectively-aggregated data (ADR-019) — knowledge-graph,
vector index, state/cache, relational — each behind a Protocol so the concrete
engine is a per-profile default, not an architectural commitment. Business logic
depends only on the Protocols; no cloud SDK is imported here.

The portable on-prem default ships in-memory, Postgres-shaped engines for every
role so no profile depends on a cloud service. Cloud profiles resolve to the same
portable engines today; concrete cloud engines slot in behind these same Protocols
as a ``providers/``-level follow-up without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mira.config.profiles import Profile, load_profile


# --------------------------------------------------------------------------- #
# Role Protocols — the seams. Business logic depends on these, never on engines.
# --------------------------------------------------------------------------- #


@runtime_checkable
class IGraphStore(Protocol):
    """Knowledge-graph store: KG nodes/edges (semantic spine; model = ADR-027)."""

    def add_node(self, node_id: str, **properties: Any) -> None: ...

    def add_edge(self, src: str, dst: str, label: str) -> None: ...

    def neighbors(self, node_id: str) -> list[str]: ...


@runtime_checkable
class IVectorIndex(Protocol):
    """Vector index: embeddings / RAG corpus."""

    def upsert(self, key: str, vector: list[float]) -> None: ...

    def search(self, vector: list[float], *, top_k: int = 5) -> list[str]: ...


@runtime_checkable
class IStateCache(Protocol):
    """State / cache: session + durable KV (memory tiers, ADR-017)."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


@runtime_checkable
class IRelationalStore(Protocol):
    """Relational: session/eval artifacts, structured metadata."""

    def insert(self, table: str, row: dict[str, Any]) -> None: ...

    def select(self, table: str, **where: Any) -> list[dict[str, Any]]: ...


# --------------------------------------------------------------------------- #
# Portable on-prem default engines — in-memory, no cloud SDK (ADR-021).
# --------------------------------------------------------------------------- #


class InMemoryGraphStore:
    """Portable graph store; stands in for a graph DB / PG-based engine on-prem."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, list[tuple[str, str]]] = {}

    def add_node(self, node_id: str, **properties: Any) -> None:
        self._nodes[node_id] = dict(properties)
        self._edges.setdefault(node_id, [])

    def add_edge(self, src: str, dst: str, label: str) -> None:
        self._edges.setdefault(src, []).append((dst, label))

    def neighbors(self, node_id: str) -> list[str]:
        return [dst for dst, _label in self._edges.get(node_id, [])]


class InMemoryVectorIndex:
    """Portable vector index; stands in for pgvector / a vector DB on-prem."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def upsert(self, key: str, vector: list[float]) -> None:
        self._vectors[key] = list(vector)

    def search(self, vector: list[float], *, top_k: int = 5) -> list[str]:
        ranked = sorted(
            self._vectors.items(),
            key=lambda item: _cosine(vector, item[1]),
            reverse=True,
        )
        return [key for key, _vec in ranked[:top_k]]


class InMemoryStateCache:
    """Portable state/cache; stands in for Redis / SQLite on-prem."""

    def __init__(self) -> None:
        self._kv: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._kv.get(key)

    def set(self, key: str, value: str) -> None:
        self._kv[key] = value


class InMemoryRelationalStore:
    """Portable relational store; Postgres-shaped row tables, no SQL engine."""

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {}

    def insert(self, table: str, row: dict[str, Any]) -> None:
        self._tables.setdefault(table, []).append(dict(row))

    def select(self, table: str, **where: Any) -> list[dict[str, Any]]:
        rows = self._tables.get(table, [])
        if not where:
            return [dict(row) for row in rows]
        return [
            dict(row)
            for row in rows
            if all(row.get(col) == val for col, val in where.items())
        ]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 when either vector is zero or lengths differ."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# Bundle + per-profile factory (ADR-021: engine = config, not architecture).


@dataclass(frozen=True, slots=True)
class StorageBundle:
    """The four storage roles resolved for a deployment profile."""

    graph: IGraphStore
    vector: IVectorIndex
    state: IStateCache
    relational: IRelationalStore


def _build_portable_bundle() -> StorageBundle:
    """On-prem portable default: in-memory engines behind every role Protocol."""
    return StorageBundle(
        graph=InMemoryGraphStore(),
        vector=InMemoryVectorIndex(),
        state=InMemoryStateCache(),
        relational=InMemoryRelationalStore(),
    )


def get_storage(profile: Profile | str | None = None) -> StorageBundle:
    """Resolve a :class:`StorageBundle` for *profile*.

    *profile* accepts a resolved :class:`~mira.config.profiles.Profile`, a profile
    name, or ``None`` to load from ``DEPLOYMENT_PROFILE``. The engine per role is a
    per-profile default; today every profile resolves to the portable on-prem
    default, so business logic stays engine-agnostic. Cloud engines slot in behind
    these same Protocols (a ``providers/`` follow-up) without changing callers.
    """
    resolved = profile if isinstance(profile, Profile) else load_profile(profile)

    # Per-profile engine selection lives here; the role Protocols are the stable
    # seam. Cloud profiles (platform == "aws") share the portable default until
    # the providers layer ships managed engines.
    _ = resolved.platform  # validated; engine selection keys off this in follow-up
    return _build_portable_bundle()


__all__ = [
    "IGraphStore",
    "IVectorIndex",
    "IStateCache",
    "IRelationalStore",
    "InMemoryGraphStore",
    "InMemoryVectorIndex",
    "InMemoryStateCache",
    "InMemoryRelationalStore",
    "StorageBundle",
    "get_storage",
]
