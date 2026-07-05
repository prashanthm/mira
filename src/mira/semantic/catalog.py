"""Catalog service: entity + pluggable-aspect metadata model (ADR-026).

The catalog inventories *what data exists and where it came from*; the
knowledge-graph spine (ADR-027) models *how domain entities relate* and consumes
catalog records as its substrate — the two are deliberately distinct components.
Following the convergent production-catalog architecture, each catalog entry is an
entity carrying named aspects (provenance, lineage, schema, quality, ...), so new
metadata kinds attach as aspects rather than schema changes. This is the offline
reference implementation behind the ADR-021 relational storage role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CatalogError(KeyError):
    """Raised on unknown entries or duplicate registration."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One catalogued entity: identity, type, and its named metadata aspects."""

    entity_id: str
    entity_type: str
    aspects: dict[str, dict[str, Any]] = field(default_factory=dict)


class Catalog:
    """Entity + pluggable-aspect catalog (ADR-026)."""

    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}

    def register(self, entry: CatalogEntry) -> None:
        """Register *entry*; re-registering an entity_id is an explicit error."""
        if not entry.entity_id:
            raise CatalogError("entity_id must be a non-empty string")
        if entry.entity_id in self._entries:
            raise CatalogError(
                f"entity {entry.entity_id!r} already registered; "
                "attach_aspect to add metadata"
            )
        self._entries[entry.entity_id] = CatalogEntry(
            entity_id=entry.entity_id,
            entity_type=entry.entity_type,
            aspects={name: dict(payload) for name, payload in entry.aspects.items()},
        )

    def attach_aspect(
        self, entity_id: str, aspect_name: str, payload: dict[str, Any]
    ) -> CatalogEntry:
        """Attach (or replace) the *aspect_name* aspect on an existing entry."""
        if not aspect_name:
            raise CatalogError("aspect_name must be a non-empty string")
        entry = self.get(entity_id)
        updated = CatalogEntry(
            entity_id=entry.entity_id,
            entity_type=entry.entity_type,
            aspects={**entry.aspects, aspect_name: dict(payload)},
        )
        self._entries[entity_id] = updated
        return updated

    def get(self, entity_id: str) -> CatalogEntry:
        """Return the entry for *entity_id*; explicit error if unknown."""
        try:
            return self._entries[entity_id]
        except KeyError:
            raise CatalogError(f"unknown catalog entity {entity_id!r}") from None

    def find(
        self, entity_type: str | None = None, aspect: str | None = None
    ) -> tuple[CatalogEntry, ...]:
        """Entries filtered by *entity_type* and/or carried *aspect*, ordered by id."""
        return tuple(
            self._entries[eid]
            for eid in sorted(self._entries)
            if (entity_type is None or self._entries[eid].entity_type == entity_type)
            and (aspect is None or aspect in self._entries[eid].aspects)
        )

    def __len__(self) -> int:
        return len(self._entries)
