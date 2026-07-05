"""Canonical entity resolution: deterministic-key-first identity (ADR-022).

Every resolved entity becomes a typed canonical node — never a generic "entity" —
matched deterministically on stable keys first: an exact key match resolves to the
existing canonical node, otherwise a new one is created. The crosswalk is
non-destructive (``link_alias`` adds a typed alias key; nothing is merged or
overwritten, and a conflicting alias is an explicit error, never a silent remap).
No fuzzy matching lives here: the bounded probabilistic fallback ADR-022 allows for
unkeyed sources is an optional ``fallback`` hook, so a Fellegi-Sunter style matcher
can plug in later without changing the deterministic tier.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


class EntityResolutionError(ValueError):
    """Raised on invalid resolution input or a conflicting (destructive) crosswalk link."""


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    """One typed canonical identity node (ADR-022): stable id, keys, aliases, attributes."""

    entity_id: str
    entity_type: str
    keys: frozenset[str]
    aliases: frozenset[str] = frozenset()
    attributes: dict[str, Any] = field(default_factory=dict)


FallbackMatcher = Callable[[str, frozenset[str]], "CanonicalEntity | None"]


def _normalize_keys(keys: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(k.strip().lower() for k in keys if k and k.strip())
    if not normalized:
        raise EntityResolutionError("resolution requires at least one non-empty key")
    return normalized


class EntityResolver:
    """Deterministic-key-first resolver over typed canonical nodes (ADR-022).

    ``fallback`` is the ADR-022 probabilistic-tier hook: consulted only when no
    deterministic key matches, before a new canonical node is created. It is not
    implemented in-tree — deterministic resolution must never depend on it.
    """

    def __init__(self, *, fallback: FallbackMatcher | None = None) -> None:
        self._fallback = fallback
        self._entities: dict[str, CanonicalEntity] = {}
        # (entity_type, key) -> entity_id: the deterministic crosswalk index.
        self._key_index: dict[tuple[str, str], str] = {}

    def resolve(
        self,
        entity_type: str,
        keys: Iterable[str],
        *,
        attributes: dict[str, Any] | None = None,
    ) -> CanonicalEntity:
        """Resolve *keys* of *entity_type* to a canonical node, creating one if new.

        Deterministic tier first: any exact (type, key) match returns the existing
        node — idempotent, and additional keys in the same call are linked to it
        non-destructively. With no match, the optional probabilistic ``fallback``
        is consulted; only then is a new canonical node created.
        """
        if not entity_type or not entity_type.strip():
            raise EntityResolutionError("entity_type must be a non-empty string")
        etype = entity_type.strip().lower()
        normalized = _normalize_keys(keys)

        matched_ids = {
            self._key_index[(etype, key)]
            for key in normalized
            if (etype, key) in self._key_index
        }
        if len(matched_ids) > 1:
            raise EntityResolutionError(
                f"keys {sorted(normalized)} match multiple canonical {etype} nodes "
                f"{sorted(matched_ids)}; refusing to merge (ADR-022 non-destructive rule)"
            )
        if matched_ids:
            entity = self._entities[matched_ids.pop()]
            return self._extend(entity, new_keys=normalized, new_attributes=attributes)

        if self._fallback is not None:
            candidate = self._fallback(etype, normalized)
            if candidate is not None:
                if candidate.entity_id not in self._entities:
                    raise EntityResolutionError(
                        f"fallback returned unknown entity {candidate.entity_id!r}"
                    )
                return self._extend(
                    self._entities[candidate.entity_id],
                    new_keys=normalized,
                    new_attributes=attributes,
                )

        entity_id = f"{etype}:{min(sorted(normalized))}"
        entity = CanonicalEntity(
            entity_id=entity_id,
            entity_type=etype,
            keys=normalized,
            attributes=dict(attributes or {}),
        )
        self._entities[entity_id] = entity
        for key in normalized:
            self._key_index[(etype, key)] = entity_id
        return entity

    def _extend(
        self,
        entity: CanonicalEntity,
        *,
        new_keys: frozenset[str],
        new_attributes: dict[str, Any] | None,
    ) -> CanonicalEntity:
        """Non-destructively add keys/attributes to an existing canonical node."""
        merged_keys = entity.keys | new_keys
        merged_attrs = dict(entity.attributes)
        for name, value in (new_attributes or {}).items():
            merged_attrs.setdefault(name, value)
        updated = CanonicalEntity(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            keys=merged_keys,
            aliases=entity.aliases,
            attributes=merged_attrs,
        )
        self._entities[entity.entity_id] = updated
        for key in merged_keys:
            self._key_index[(entity.entity_type, key)] = entity.entity_id
        return updated

    def link_alias(self, entity_id: str, alias_key: str) -> CanonicalEntity:
        """Link *alias_key* to an existing canonical node — the non-destructive crosswalk.

        The alias becomes a resolvable key for the node. Linking an alias already
        owned by a *different* node of the same type is an explicit error: the
        crosswalk never silently remaps identity (ADR-022).
        """
        entity = self.get(entity_id)
        alias = alias_key.strip().lower()
        if not alias:
            raise EntityResolutionError("alias_key must be a non-empty string")
        owner = self._key_index.get((entity.entity_type, alias))
        if owner is not None and owner != entity_id:
            raise EntityResolutionError(
                f"alias {alias!r} already resolves to {owner!r}; refusing to remap to "
                f"{entity_id!r} (ADR-022 non-destructive rule)"
            )
        updated = CanonicalEntity(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            keys=entity.keys | {alias},
            aliases=entity.aliases | {alias},
            attributes=entity.attributes,
        )
        self._entities[entity_id] = updated
        self._key_index[(entity.entity_type, alias)] = entity_id
        return updated

    def get(self, entity_id: str) -> CanonicalEntity:
        """Return the canonical node with *entity_id*; explicit error if unknown."""
        try:
            return self._entities[entity_id]
        except KeyError:
            raise EntityResolutionError(f"unknown entity {entity_id!r}") from None

    def lookup(self, entity_type: str, keys: Iterable[str]) -> CanonicalEntity | None:
        """Non-creating deterministic lookup: the matching node, or None."""
        etype = entity_type.strip().lower()
        for key in _normalize_keys(keys):
            entity_id = self._key_index.get((etype, key))
            if entity_id is not None:
                return self._entities[entity_id]
        return None

    def entities(self) -> tuple[CanonicalEntity, ...]:
        """All canonical nodes, ordered by entity_id."""
        return tuple(self._entities[eid] for eid in sorted(self._entities))
