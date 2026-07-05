"""Dependency-free BM25 lexical index — the sparse half of hybrid retrieval (ADR-028).

Implements the standard Okapi BM25 ranking function (``k1`` term-frequency
saturation, ``b`` length normalization, smoothed idf that never goes negative)
with the same ``add``/``search`` surface as the dense :class:`~mira.retrieval.protocols.VectorIndex`
Protocol, so the hybrid fuser treats both rankers uniformly. Exact-token matching
catches the identifiers and rare terms dense retrieval blurs; only documents
sharing at least one query term are scored, so a fully out-of-vocabulary query
returns no hits. Document frequencies are exposed (``document_frequency``/``idf``)
because ADR-029's default query-relaxation rewriter drops out-of-vocabulary tokens.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from mira.retrieval.inmemory import tokenize
from mira.retrieval.protocols import SearchHit


@dataclass(frozen=True, slots=True)
class _SparseDoc:
    doc_id: str
    text: str
    metadata: dict[str, Any]
    term_counts: Counter[str]
    length: int


class Bm25Index:
    """BM25 lexical index with the uniform add/search surface (ADR-028 sparse ranker)."""

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError(f"invalid BM25 params: k1={k1}, b={b}")
        self.k1 = k1
        self.b = b
        self._docs: dict[str, _SparseDoc] = {}

    def add(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        """Index *text* under *doc_id*; re-adding a doc_id replaces the prior entry."""
        if not doc_id:
            raise ValueError("doc_id must be a non-empty string")
        tokens = tokenize(text)
        self._docs[doc_id] = _SparseDoc(
            doc_id=doc_id,
            text=text,
            metadata=dict(metadata),
            term_counts=Counter(tokens),
            length=len(tokens),
        )

    def document_frequency(self, term: str) -> int:
        """Number of indexed documents containing *term* (lowercased exact token)."""
        needle = term.lower()
        return sum(1 for doc in self._docs.values() if needle in doc.term_counts)

    def idf(self, term: str) -> float:
        """Smoothed inverse document frequency of *term* (always positive)."""
        n = len(self._docs)
        df = self.document_frequency(term)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int) -> list[SearchHit]:
        """Return up to *k* BM25-scored hits, best first (ties broken by doc_id).

        Only documents containing at least one query term are scored.
        """
        if k <= 0 or not self._docs:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        avg_len = sum(doc.length for doc in self._docs.values()) / len(self._docs)
        scored: list[SearchHit] = []
        for doc in self._docs.values():
            score = 0.0
            for term in terms:
                tf = doc.term_counts.get(term, 0)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * doc.length / max(avg_len, 1e-9))
                score += self.idf(term) * tf * (self.k1 + 1) / denom
            if score > 0.0:
                scored.append(
                    SearchHit(doc_id=doc.doc_id, score=score, text=doc.text, metadata=doc.metadata)
                )
        scored.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return scored[:k]

    def __len__(self) -> int:
        return len(self._docs)
