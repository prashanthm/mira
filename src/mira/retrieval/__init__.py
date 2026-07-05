"""Retrieval pipeline — hybrid dense+sparse search with agentic correction (ADR-028, ADR-029).

The ADR-002/ADR-021 storage seam lives in ``protocols``: dependency-free reference
implementations (``inmemory``, ``sparse``) sit behind the same Protocols a
pgvector/OpenSearch backend would implement under ``providers/`` later. ``hybrid``
fuses dense and sparse rankings with Reciprocal Rank Fusion (ADR-028); ``agentic``
wraps the hybrid retriever in a bounded retrieve→grade→re-query loop (ADR-029).
Nothing here imports orchestration or vendor SDKs.
"""

from mira.retrieval.agentic import CorrectiveRetriever, RetrievalOutcome
from mira.retrieval.hybrid import HybridRetriever, index_corpus
from mira.retrieval.inmemory import HashEmbedder, InMemoryVectorIndex
from mira.retrieval.protocols import Embedder, SearchHit, VectorIndex
from mira.retrieval.sparse import Bm25Index

__all__ = [
    "Bm25Index",
    "CorrectiveRetriever",
    "Embedder",
    "HashEmbedder",
    "HybridRetriever",
    "InMemoryVectorIndex",
    "RetrievalOutcome",
    "SearchHit",
    "VectorIndex",
    "index_corpus",
]
