"""Skills registry: versioned, authorized composed capabilities (ADR-032).

A **skill** is a named, versioned composition of one or more ADR-031 typed tool
contracts — a governed unit above one-off tools, distinct from an ADR-035 agent
card's routing metadata. This module implements ADR-032's registration model:

* **Immutable versions** — re-registering an existing ``(name, version)`` raises,
  mirroring the ADR-012 registry semantics (`mira.model.versioning.Registry`).
* **Entitlement union** — a skill's required entitlements are derived at
  registration as the union of its composed tools' declared entitlements
  (ADR-032 §4): composition never escalates privilege, and a skill whose tool
  names do not all resolve to contracts is rejected outright.
* **Fail-closed authorization** — :meth:`SkillsRegistry.authorize` grants only
  when *every* required entitlement is covered; an unregistered skill is never
  authorized.

Version resolution with ``version=None`` picks the highest registered version by
a simple dotted-numeric tuple compare (non-numeric segments compare as strings
after numeric segments) — adequate for the MAJOR.MINOR.PATCH scheme ADR-032
commits to; a full SemVer comparator can replace ``_version_key`` without
changing the registry contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from mira.tools.contract import ToolContract


class SkillsError(Exception):
    """Base error for skills registry operations."""


class SkillVersionExists(SkillsError):
    """Raised when re-registering an existing (name, version) — versions are immutable."""


class UnknownSkillError(SkillsError):
    """Raised when a skill name (or name/version pair) is not registered."""


class UnresolvedToolError(SkillsError):
    """Raised when a skill names a tool that the provided contract lookup cannot resolve."""


@dataclass(frozen=True, slots=True)
class Skill:
    """A named, versioned composition of ADR-031 tool contracts (ADR-032).

    ``required_entitlements`` is *derived*, not author-declared: the registry
    aggregates it from the composed contracts at registration time, so a skill
    can never declare broader privilege than its parts require.
    """

    name: str
    version: str
    description: str
    tool_names: tuple[str, ...]
    required_entitlements: frozenset[str] = field(default_factory=frozenset)


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key for dotted versions: numeric segments compare numerically.

    Each segment maps to ``(0, int)`` when numeric or ``(1, str)`` otherwise, so
    ``"2.10.0" > "2.9.1"`` and comparison never raises on mixed segments.
    """
    key: list[tuple[int, int | str]] = []
    for segment in version.split("."):
        if segment.isdigit():
            key.append((0, int(segment)))
        else:
            key.append((1, segment))
    return tuple(key)


class SkillsRegistry:
    """Registry of immutable skill versions with derived, fail-closed authorization."""

    def __init__(self) -> None:
        self._skills: dict[str, dict[str, Skill]] = {}

    def register(self, skill: Skill, contracts: Mapping[str, ToolContract]) -> Skill:
        """Register ``skill``, validating its composition against ``contracts``.

        Every ``tool_names`` entry must resolve to a :class:`ToolContract` in
        ``contracts``; the stored skill's ``required_entitlements`` is the union
        of the resolved contracts' declared entitlements (ADR-032 §4). Versions
        are immutable: re-registering an existing ``(name, version)`` raises
        :class:`SkillVersionExists` (ADR-012 semantics). Returns the stored
        skill (with entitlements aggregated).
        """
        if not skill.name:
            raise SkillsError("skill name must be non-empty")
        if not skill.version:
            raise SkillsError(f"skill {skill.name!r} must declare a version")
        if not skill.tool_names:
            raise SkillsError(
                f"skill {skill.name!r} must compose at least one tool (ADR-032)"
            )

        missing = [name for name in skill.tool_names if name not in contracts]
        if missing:
            raise UnresolvedToolError(
                f"skill {skill.name!r} composes unknown tools: {sorted(missing)}"
            )

        versions = self._skills.setdefault(skill.name, {})
        if skill.version in versions:
            raise SkillVersionExists(
                f"Version {skill.version!r} for skill {skill.name!r} already "
                "registered; versions are immutable (ADR-032/ADR-012)"
            )

        entitlements = frozenset(
            contracts[name].required_entitlement for name in skill.tool_names
        )
        stored = replace(skill, required_entitlements=entitlements)
        versions[skill.version] = stored
        return stored

    def resolve(self, name: str, version: str | None = None) -> Skill:
        """Return the skill registered as ``name``.

        ``version=None`` resolves the highest registered version (see module
        docstring for the compare); a named version must exist exactly.
        """
        versions = self._skills.get(name)
        if not versions:
            raise UnknownSkillError(f"no skill registered as {name!r}")
        if version is None:
            highest = max(versions, key=_version_key)
            return versions[highest]
        if version not in versions:
            raise UnknownSkillError(
                f"skill {name!r} has no version {version!r} "
                f"(registered: {sorted(versions)})"
            )
        return versions[version]

    def authorize(self, skill: Skill, granted_entitlements: set[str]) -> bool:
        """Fail-closed authorization: every required entitlement must be granted.

        Authorization is decided against the *registered* skill (the one whose
        entitlements this registry derived) — an unregistered skill, or one
        whose registered entitlement union is not fully covered by
        ``granted_entitlements``, is denied.
        """
        registered = self._skills.get(skill.name, {}).get(skill.version)
        if registered is None:
            return False
        return registered.required_entitlements <= granted_entitlements

    def skills(self) -> tuple[Skill, ...]:
        """All registered skill versions, ordered by name then version."""
        return tuple(
            versions[version]
            for name in sorted(self._skills)
            for versions in (self._skills[name],)
            for version in sorted(versions, key=_version_key)
        )


__all__ = [
    "Skill",
    "SkillsError",
    "SkillsRegistry",
    "SkillVersionExists",
    "UnknownSkillError",
    "UnresolvedToolError",
]
