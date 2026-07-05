"""Graph + vector fusion: entity-aware grounding over hybrid retrieval (ADR-030).

Vector retrieval finds text that looks like the question; it does not know which
canonical entity a chunk describes or what that entity is connected to.
:class:`GraphVectorFusion` closes that gap deterministically and structurally:
each ADR-028 hybrid hit is resolved to its canonical entity (ADR-022, via the hit's
anchor/metadata keys — a non-creating lookup, never a resolution side effect), and
the entity's 1-hop graph neighborhood (ADR-027 spine) is appended as context
records. Every fused result carries both the retrieval score and the graph
provenance of each context edge, so entity-level claims stay attributable
(ADR-025, ADR-040). No model calls, no extraction pipeline: the graph is built by
the :mod:`mira.semantic.kg` builders, and fusion is a pure structural join.
"""

from __future__ import annotations

from dataclasses import dataclass

from mira.connectors.base import Provenance
from mira.retrieval.hybrid import HybridRetriever
from mira.retrieval.protocols import SearchHit
from mira.semantic.entities import EntityResolver
from mira.semantic.kg import KnowledgeGraph


@dataclass(frozen=True, slots=True)
class GraphContext:
    """One 1-hop graph neighbor of a hit's entity: the edge, spelled out with provenance."""

    entity_id: str
    entity_type: str
    predicate: str
    direction: str  # "out" (entity --pred--> neighbor) or "in" (neighbor --pred--> entity)
    provenance: Provenance | None = None


@dataclass(frozen=True, slots=True)
class FusedHit:
    """A retrieval hit expanded with canonical identity and graph context (ADR-030)."""

    hit: SearchHit
    entity_id: str | None
    context: tuple[GraphContext, ...] = ()


class GraphVectorFusion:
    """Fuses ADR-028 hybrid hits with ADR-027 graph neighborhoods (ADR-030)."""

    def __init__(
        self,
        retriever: HybridRetriever,
        graph: KnowledgeGraph,
        resolver: EntityResolver,
        *,
        entity_type: str = "section",
    ) -> None:
        self._retriever = retriever
        self._graph = graph
        self._resolver = resolver
        self._entity_type = entity_type

    def answer(self, query: str, k: int = 3) -> list[FusedHit]:
        """Retrieve *k* hybrid hits and expand each with its entity's 1-hop neighborhood.

        A hit resolves to a canonical entity through its ``anchor`` metadata (or its
        doc_id) via a non-creating lookup; a hit with no resolvable entity, or an
        entity absent from the graph, is returned with empty context rather than
        dropped — retrieval evidence is never discarded by fusion. Retrieval order
        (and each hit's retrieval score) is preserved; graph context adds to it.
        """
        fused: list[FusedHit] = []
        for hit in self._retriever.search(query, k):
            key = hit.metadata.get("anchor") or hit.doc_id
            entity = self._resolver.lookup(self._entity_type, [str(key)])
            if entity is None or not self._graph.has_node(entity.entity_id):
                fused.append(FusedHit(hit=hit, entity_id=None))
                continue
            context = []
            for edge in self._graph.neighbors(entity.entity_id):
                if edge.subject_id == entity.entity_id:
                    neighbor_id, direction = edge.object_id, "out"
                else:
                    neighbor_id, direction = edge.subject_id, "in"
                neighbor = self._graph.node(neighbor_id)
                context.append(
                    GraphContext(
                        entity_id=neighbor.entity_id,
                        entity_type=neighbor.entity_type,
                        predicate=edge.predicate,
                        direction=direction,
                        provenance=edge.provenance,
                    )
                )
            fused.append(
                FusedHit(hit=hit, entity_id=entity.entity_id, context=tuple(context))
            )
        return fused
