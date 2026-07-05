"""Startup profile validation and degraded-mode fallback (ADR-047/048)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

LOCAL_PROFILE = "local"

T = TypeVar("T")


class ConfigValidationError(ValueError):
    """Raised when resolved profile configuration is unsafe for the target profile."""


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    """Profile name plus auth-related settings resolved at startup."""

    profile: str
    skip_auth: bool = False


@dataclass
class DegradedModeSignal:
    """Mutable signal emitted when a degraded-mode fallback path is taken."""

    degraded_mode: bool = False


def validate(config: ProfileConfig) -> None:
    """Reject unsafe configuration combinations before startup continues."""
    if config.skip_auth and config.profile != LOCAL_PROFILE:
        raise ConfigValidationError(
            f"skip_auth is only permitted for the {LOCAL_PROFILE!r} profile; "
            f"got profile={config.profile!r}"
        )


# Operational failures that warrant graceful degradation (dependency
# unavailability). Programming errors (TypeError, AttributeError, ValueError,
# KeyError, ...) are intentionally excluded so misconfiguration/bugs fail fast
# per ADR-047, rather than silently flipping into degraded mode (ADR-048 §4).
DEFAULT_DEGRADE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OSError,
    ConnectionError,
    TimeoutError,
    RuntimeError,
)


def with_degraded_fallback(
    primary: Callable[[], T],
    alt: Callable[[], T],
    signal: DegradedModeSignal,
    exceptions: tuple[type[BaseException], ...] = DEFAULT_DEGRADE_EXCEPTIONS,
) -> T:
    """Try ``primary``; on an operational failure resolve via ``alt`` and emit
    ``degraded_mode``.

    Only exceptions in ``exceptions`` (operational/dependency failures by
    default) trigger fallback. Programming errors propagate so misconfiguration
    fails fast instead of degrading silently.
    """
    try:
        return primary()
    except exceptions:
        signal.degraded_mode = True
        return alt()
