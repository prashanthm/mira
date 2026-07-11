"""Versioned prompt/tool registry with eval-gated promotion and kill switch (ADR-012).

Extracted to the agent-agnostic harness plane (ADR-050); ``mira.model.versioning``
re-exports from here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Environment = Literal["dev", "staging", "prod"]

_PREVIOUS_ENV: dict[Environment, Environment | None] = {
    "dev": None,
    "staging": "dev",
    "prod": "staging",
}


class VersioningError(Exception):
    """Base error for registry versioning operations."""


class VersionNotFound(VersioningError):
    """Raised when a key/version pair is missing from the registry."""


class PromotionError(VersioningError):
    """Raised when a promotion prerequisite is not satisfied."""


class EvalGateFailed(PromotionError):
    """Raised when eval_gate rejects a staging/prod promotion."""


class KillSwitchError(VersioningError):
    """Raised when no last-known-good version exists for kill-switch revert."""


@dataclass(frozen=True, slots=True)
class VersionedArtifact:
    """Immutable versioned prompt or tool definition."""

    key: str
    version: str
    content: dict[str, Any]


class Registry:
    """Store versioned artifacts and resolve the active version per environment."""

    def __init__(self) -> None:
        self._artifacts: dict[str, dict[str, dict[str, Any]]] = {}
        self._active: dict[str, dict[Environment, str]] = {}
        self._last_good: dict[str, dict[Environment, str]] = {}

    def register(self, key: str, version: str, content: dict[str, Any]) -> None:
        """Store an immutable version for key.

        Versions are immutable (ADR-012): re-registering an existing
        ``(key, version)`` raises rather than silently overwriting content.
        """
        existing = self._artifacts.setdefault(key, {})
        if version in existing:
            raise PromotionError(
                f"Version {version!r} for {key!r} already registered; "
                "versions are immutable (ADR-012)"
            )
        existing[version] = dict(content)

    def resolve(self, key: str, env: Environment) -> VersionedArtifact:
        """Return the active artifact for key in env."""
        version = self._active.get(key, {}).get(env)
        if version is None:
            raise VersionNotFound(f"No active version for {key!r} in {env!r}")

        try:
            content = self._artifacts[key][version]
        except KeyError as exc:
            raise VersionNotFound(
                f"Active version {version!r} for {key!r} is not registered"
            ) from exc

        return VersionedArtifact(key=key, version=version, content=dict(content))

    def promote(
        self,
        key: str,
        version: str,
        env: Environment,
        eval_gate: Callable[[], bool],
    ) -> None:
        """Advance version to env along dev→staging→prod; gate staging/prod on eval_gate().

        Promotion into ``dev`` is not eval-gated (it has no previous env); only
        staging and prod promotions invoke ``eval_gate`` (ADR-012).
        """
        if version not in self._artifacts.get(key, {}):
            raise VersionNotFound(f"Version {version!r} for {key!r} is not registered")

        previous_env = _PREVIOUS_ENV[env]
        if previous_env is not None:
            if self._active.get(key, {}).get(previous_env) != version:
                raise PromotionError(
                    f"Version {version!r} must be active in {previous_env!r} before {env!r}"
                )
            if not eval_gate():
                raise EvalGateFailed(
                    f"Eval gate rejected promotion of {version!r} for {key!r} to {env!r}"
                )

        current = self._active.setdefault(key, {}).get(env)
        if current is not None and current != version:
            self._last_good.setdefault(key, {})[env] = current

        self._active[key][env] = version

    def kill_switch(self, key: str, env: Environment) -> None:
        """Revert active pointer to last-known-good without redeploy."""
        last_good = self._last_good.get(key, {}).get(env)
        if last_good is None:
            raise KillSwitchError(
                f"No last-known-good version for {key!r} in {env!r}"
            )
        if last_good not in self._artifacts.get(key, {}):
            raise KillSwitchError(
                f"Last-known-good version {last_good!r} for {key!r} is not registered"
            )
        self._active.setdefault(key, {})[env] = last_good
