"""In-memory knowledge-graph spine: typed nodes, predicate edges, builders (ADR-027).

The semantic spine above the connectors (ADR-019 Rule 4): canonical typed nodes
(ADR-022) linked by predicate edges, each edge optionally carrying
:class:`~mira.connectors.base.Provenance` so cross-source entity links stay
attributable (ADR-025, ADR-040). This is the offline reference implementation of
the ADR-021 knowledge-graph store role; a managed graph engine implements the same
shape under ``providers/`` later.

Builders populate the spine from the demo connectors' parsed documents:
``graph_from_ledger`` (Account/Category/Entry nodes, ``posted_to``/``in_category``
edges) and ``graph_from_docs`` (Document/Section nodes, ``has_section`` edges,
plus ``mentions`` edges when one section's body references another's title).
"""

from __future__ import annotations

from dataclasses import dataclass

from mira.connectors.base import Provenance
from mira.connectors.docs import DocsDocument
from mira.connectors.ledger import LedgerDocument
from mira.semantic.entities import CanonicalEntity, EntityResolver


class KnowledgeGraphError(ValueError):
    """Raised on invalid graph operations (unknown node, dangling edge)."""


@dataclass(frozen=True, slots=True)
class Edge:
    """One directed triple: subject --predicate--> object, with optional provenance."""

    subject_id: str
    predicate: str
    object_id: str
    provenance: Provenance | None = None


class KnowledgeGraph:
    """In-memory triple store over canonical entities (ADR-027 spine)."""

    def __init__(self) -> None:
        self._nodes: dict[str, CanonicalEntity] = {}
        self._edges: list[Edge] = []

    def add_node(self, entity: CanonicalEntity) -> None:
        """Add (or refresh) the canonical node *entity*; keyed by entity_id."""
        self._nodes[entity.entity_id] = entity

    def add_edge(
        self,
        subject_id: str,
        predicate: str,
        object_id: str,
        provenance: Provenance | None = None,
    ) -> Edge:
        """Add the triple ``subject --predicate--> object``; both nodes must exist."""
        if not predicate or not predicate.strip():
            raise KnowledgeGraphError("predicate must be a non-empty string")
        for entity_id in (subject_id, object_id):
            if entity_id not in self._nodes:
                raise KnowledgeGraphError(
                    f"cannot add edge: unknown node {entity_id!r} (add_node first)"
                )
        edge = Edge(
            subject_id=subject_id,
            predicate=predicate.strip(),
            object_id=object_id,
            provenance=provenance,
        )
        if edge not in self._edges:
            self._edges.append(edge)
        return edge

    def node(self, entity_id: str) -> CanonicalEntity:
        """Return the node with *entity_id*; explicit error if unknown."""
        try:
            return self._nodes[entity_id]
        except KeyError:
            raise KnowledgeGraphError(f"unknown node {entity_id!r}") from None

    def has_node(self, entity_id: str) -> bool:
        """True when *entity_id* is a node in the graph."""
        return entity_id in self._nodes

    def edges(self) -> tuple[Edge, ...]:
        """All edges, in insertion order."""
        return tuple(self._edges)

    def neighbors(self, entity_id: str, predicate: str | None = None) -> tuple[Edge, ...]:
        """Edges touching *entity_id* in either direction, optionally by *predicate*.

        Returned as edges (not bare nodes) so callers keep direction, predicate,
        and provenance — the graph context ADR-030 fusion attaches to hits.
        """
        self.node(entity_id)
        return tuple(
            edge
            for edge in self._edges
            if entity_id in (edge.subject_id, edge.object_id)
            and (predicate is None or edge.predicate == predicate)
        )

    def subgraph(self, entity_id: str, depth: int) -> KnowledgeGraph:
        """The subgraph reachable from *entity_id* within *depth* hops (either direction)."""
        if depth < 0:
            raise KnowledgeGraphError(f"depth must be non-negative, got {depth}")
        self.node(entity_id)
        reached = {entity_id}
        frontier = {entity_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for node_id in frontier:
                for edge in self.neighbors(node_id):
                    for other in (edge.subject_id, edge.object_id):
                        if other not in reached:
                            next_frontier.add(other)
            reached |= next_frontier
            frontier = next_frontier
            if not frontier:
                break
        sub = KnowledgeGraph()
        for node_id in reached:
            sub.add_node(self._nodes[node_id])
        for edge in self._edges:
            if edge.subject_id in reached and edge.object_id in reached:
                sub._edges.append(edge)
        return sub

    def __len__(self) -> int:
        return len(self._nodes)


def graph_from_ledger(
    document: LedgerDocument, resolver: EntityResolver, *, source_id: str = "ledger"
) -> KnowledgeGraph:
    """Build the finance spine: Account/Category/Entry nodes with posting edges.

    Every entry becomes an Entry node linked ``posted_to`` its Account and
    ``in_category`` its Category; edge provenance carries the ledger source and
    the entry currency as its unit (ADR-023's concern travels with the edge).
    """
    graph = KnowledgeGraph()
    for index, entry in enumerate(document.entries):
        account = resolver.resolve("account", [entry.account])
        category = resolver.resolve("category", [entry.category])
        entry_node = resolver.resolve(
            "entry",
            [f"{source_id}:{index}"],
            attributes={
                "date": entry.date,
                "amount": entry.amount,
                "currency": entry.currency,
            },
        )
        provenance = Provenance(
            source_type="ledger", source_id=source_id, units=entry.currency
        )
        graph.add_node(account)
        graph.add_node(category)
        graph.add_node(entry_node)
        graph.add_edge(entry_node.entity_id, "posted_to", account.entity_id, provenance)
        graph.add_edge(entry_node.entity_id, "in_category", category.entity_id, provenance)
    return graph


def graph_from_docs(
    document: DocsDocument, resolver: EntityResolver, *, source_id: str = "docs"
) -> KnowledgeGraph:
    """Build the research spine: Document/Section nodes with containment + mention edges.

    The document node links ``has_section`` to each section; when one section's
    body mentions another section's title (case-insensitive), a ``mentions``
    cross-reference edge is added. Edge provenance carries the section anchor so
    graph context stays citable (ADR-025, ADR-040).
    """
    graph = KnowledgeGraph()
    doc_key = document.headers.get("title") or source_id
    doc_node = resolver.resolve("document", [doc_key], attributes=dict(document.headers))
    graph.add_node(doc_node)

    section_nodes: dict[str, CanonicalEntity] = {}
    for section in document.sections:
        node = resolver.resolve(
            "section", [section.anchor], attributes={"title": section.title}
        )
        section_nodes[section.anchor] = node
        graph.add_node(node)
        graph.add_edge(
            doc_node.entity_id,
            "has_section",
            node.entity_id,
            Provenance(source_type="docs", source_id=f"{source_id}#{section.anchor}"),
        )

    for section in document.sections:
        body = section.body.lower()
        for other in document.sections:
            if other.anchor != section.anchor and other.title.lower() in body:
                graph.add_edge(
                    section_nodes[section.anchor].entity_id,
                    "mentions",
                    section_nodes[other.anchor].entity_id,
                    Provenance(source_type="docs", source_id=f"{source_id}#{section.anchor}"),
                )
    return graph
