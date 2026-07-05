"""Semantic spine — canonical identity, knowledge graph, catalog, conflicts, fusion.

The knowledge layer above the connectors: deterministic-key-first entity
resolution (ADR-022), the in-memory knowledge-graph spine (ADR-027), the
entity + pluggable-aspect catalog (ADR-026), measurement-vs-derived conflict
surfacing (ADR-025), and graph + vector fusion over the ADR-028 retriever
(ADR-030). Dependency-free business layer: nothing here imports orchestration
frameworks or vendor SDKs (ADR-001/ADR-002).
"""

from mira.semantic.catalog import Catalog, CatalogEntry
from mira.semantic.conflicts import Claim, Conflict, surface_conflicts
from mira.semantic.entities import CanonicalEntity, EntityResolutionError, EntityResolver
from mira.semantic.fusion import FusedHit, GraphContext, GraphVectorFusion
from mira.semantic.kg import Edge, KnowledgeGraph, graph_from_docs, graph_from_ledger

__all__ = [
    "CanonicalEntity",
    "Catalog",
    "CatalogEntry",
    "Claim",
    "Conflict",
    "Edge",
    "EntityResolutionError",
    "EntityResolver",
    "FusedHit",
    "GraphContext",
    "GraphVectorFusion",
    "KnowledgeGraph",
    "graph_from_docs",
    "graph_from_ledger",
    "surface_conflicts",
]
