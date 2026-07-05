"""Retrieval storage seam: Protocols every retrieval backend implements (ADR-021, ADR-028).

ADR-021 commits to storage *roles* behind Protocols, never to engines. These are the
vector-index role's seam: the in-tree reference implementations (:mod:`mira.retrieval.inmemory`,
:mod:`mira.retrieval.sparse`) are dependency-free, and a pgvector/OpenSearch backend
implements the same Protocols under ``providers/`` later without touching business logic
(ADR-002). Every hit carries a metadata dict so provenance (source identifiers, section
anchors) travels with retrieval results end-to-end (ADR-025, ADR-040).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One retrieval result: document id, relevance score, text, and provenance metadata."""

    doc_id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Embedder(Protocol):
    """Maps text to a fixed-dimension vector (ADR-021 vector-index role input)."""

    def embed(self, text: str) -> tuple[float, ...]:
        """Return the embedding vector for *text*; deterministic for equal input."""
        ...


@runtime_checkable
class VectorIndex(Protocol):
    """Add/search seam for a vector store (ADR-021 vector-index role).

    Reference implementation: :class:`mira.retrieval.inmemory.InMemoryVectorIndex`.
    A pgvector/OpenSearch backend is a later ``providers/`` implementation of this
    same Protocol — an engine choice per deployment profile, not an architecture change.
    """

    def add(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        """Index *text* under *doc_id*; *metadata* is returned verbatim on hits."""
        ...

    def search(self, query: str, k: int) -> list[SearchHit]:
        """Return up to *k* hits for *query*, best first."""
        ...
