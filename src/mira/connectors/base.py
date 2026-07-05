"""Source connector framework: uniform shape + registry (ADR-020).

A :class:`SourceConnector` is an anti-corruption adapter that translates one source
type (document stores, ledgers, warehouses, event streams, time-series systems) into a uniform internal shape. Every
record carries :class:`Provenance` (source attribution + units/reference-frame) so the semantic
spine can reconcile and grounding can attribute — source data is treated as
untrusted. Vendor SDKs stay in ``providers/`` (ADR-002); nothing here imports them.

The module-level :data:`registry` resolves a connector factory by source type, so a
new source is added by registering a new adapter rather than touching business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


class UnknownSourceTypeError(KeyError):
    """Raised when the registry cannot resolve a connector for a source type."""

    def __init__(self, source_type: str, *, known: tuple[str, ...] = ()) -> None:
        self.source_type = source_type
        self.known = known
        known_msg = ", ".join(sorted(known)) if known else "<none registered>"
        super().__init__(
            f"no connector registered for source type {source_type!r} "
            f"(known: {known_msg})"
        )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Source attribution + units/CRS metadata travelling with every record.

    Preserved end-to-end so the semantic spine can reconcile heterogeneous sources
    and grounding can attribute (ADR-020); source data is treated as untrusted.
    """

    source_type: str
    source_id: str
    units: str | None = None
    crs: str | None = None


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Uniform record shape returned by every connector, regardless of source."""

    provenance: Provenance
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceDescription:
    """Self-description of a connector's source: type + advertised capabilities."""

    source_type: str
    capabilities: tuple[str, ...] = ()


@runtime_checkable
class SourceConnector(Protocol):
    """Uniform interface every source adapter implements (ADR-020).

    ``describe`` advertises the source type + capabilities; ``query`` translates a
    source-specific request into a uniform sequence of :class:`SourceRecord`.
    """

    def describe(self) -> SourceDescription:
        """Return the connector's source type and advertised capabilities."""
        ...

    def query(self, request: dict[str, Any]) -> list[SourceRecord]:
        """Execute a query against the source, returning records in uniform shape."""
        ...


ConnectorFactory = Callable[[], SourceConnector]


class ConnectorRegistry:
    """Resolves connector factories by source type — add a source by registering one."""

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, source_type: str, factory: ConnectorFactory) -> None:
        """Register ``factory`` for ``source_type``; later registration overrides."""
        if not source_type:
            raise ValueError("source_type must be a non-empty string")
        self._factories[source_type] = factory

    def resolve(self, source_type: str) -> SourceConnector:
        """Instantiate and return the connector for ``source_type``.

        Raises :class:`UnknownSourceTypeError` if no factory is registered.
        """
        try:
            factory = self._factories[source_type]
        except KeyError:
            raise UnknownSourceTypeError(
                source_type, known=tuple(self._factories)
            ) from None
        return factory()

    def source_types(self) -> tuple[str, ...]:
        """Return the registered source types in sorted order."""
        return tuple(sorted(self._factories))


registry = ConnectorRegistry()
