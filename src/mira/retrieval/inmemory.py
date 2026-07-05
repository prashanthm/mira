"""In-memory reference implementations of the retrieval Protocols (ADR-021, ADR-028).

:class:`HashEmbedder` is a deterministic, dependency-free embedding: token and
character-trigram features are CRC32-hashed into a fixed number of buckets and the
count vector is L2-normalized. Trigram features give it tolerance to morphological
variance ("override" vs "overridable") that exact-token sparse retrieval lacks —
which is precisely the complementary signal ADR-028's fusion relies on. CRC32 is
stable across processes and platforms, so offline tests are reproducible (unlike
Python's randomized ``hash()``).

:class:`InMemoryVectorIndex` performs cosine-similarity search over stored vectors.
Both are per-profile defaults behind the :mod:`mira.retrieval.protocols` seam; a
real embedding model and a pgvector/OpenSearch index swap in under ``providers/``
without touching callers (ADR-002).
"""

from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass
from typing import Any

from mira.retrieval.protocols import SearchHit

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens of *text* — the shared tokenizer for dense and sparse."""
    return _TOKEN_RE.findall(text.lower())


def _features(token: str) -> list[str]:
    """A token's hashing features: the token itself plus its character trigrams."""
    feats = [token]
    if len(token) > 3:
        feats.extend(token[i : i + 3] for i in range(len(token) - 2))
    return feats


@dataclass(frozen=True, slots=True)
class HashEmbedder:
    """Deterministic token/trigram-hash embedding over a fixed dimension."""

    dimension: int = 256

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError(f"dimension must be positive, got {self.dimension}")

    def embed(self, text: str) -> tuple[float, ...]:
        """Return the L2-normalized bucket-count vector for *text* (zero vector if empty)."""
        counts = [0.0] * self.dimension
        for token in tokenize(text):
            for feature in _features(token):
                bucket = zlib.crc32(feature.encode("utf-8")) % self.dimension
                counts[bucket] += 1.0
        norm = math.sqrt(sum(c * c for c in counts))
        if norm == 0.0:
            return tuple(counts)
        return tuple(c / norm for c in counts)


@dataclass(frozen=True, slots=True)
class _StoredDoc:
    doc_id: str
    text: str
    metadata: dict[str, Any]
    vector: tuple[float, ...]


class InMemoryVectorIndex:
    """Cosine-similarity vector index — the offline default for the ADR-021 vector role."""

    def __init__(self, embedder: Any | None = None) -> None:
        self._embedder = embedder if embedder is not None else HashEmbedder()
        self._docs: dict[str, _StoredDoc] = {}

    def add(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        """Index *text* under *doc_id*; re-adding a doc_id replaces the prior entry."""
        if not doc_id:
            raise ValueError("doc_id must be a non-empty string")
        self._docs[doc_id] = _StoredDoc(
            doc_id=doc_id, text=text, metadata=dict(metadata), vector=self._embedder.embed(text)
        )

    def search(self, query: str, k: int) -> list[SearchHit]:
        """Return up to *k* hits by descending cosine similarity (ties broken by doc_id).

        Zero-similarity documents are excluded: a query sharing nothing with the
        corpus returns no hits rather than an arbitrary ranking.
        """
        if k <= 0:
            return []
        query_vec = self._embedder.embed(query)
        scored: list[SearchHit] = []
        for doc in self._docs.values():
            score = sum(q * d for q, d in zip(query_vec, doc.vector))
            if score > 0.0:
                scored.append(
                    SearchHit(doc_id=doc.doc_id, score=score, text=doc.text, metadata=doc.metadata)
                )
        scored.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return scored[:k]

    def __len__(self) -> int:
        return len(self._docs)
