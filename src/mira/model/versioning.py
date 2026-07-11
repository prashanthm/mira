"""Shim (ADR-050): versioning moved to :mod:`mira_harness.versioning`.

Re-exports only — never fork this module; new symbols land in the new home.
"""

from __future__ import annotations

from mira_harness.versioning import (
    Environment,
    EvalGateFailed,
    KillSwitchError,
    PromotionError,
    Registry,
    VersionedArtifact,
    VersioningError,
    VersionNotFound,
)

__all__ = [
    "Environment",
    "EvalGateFailed",
    "KillSwitchError",
    "PromotionError",
    "Registry",
    "VersionNotFound",
    "VersionedArtifact",
    "VersioningError",
]
