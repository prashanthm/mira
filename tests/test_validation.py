import pytest

from mira.config.validation import (
    ConfigValidationError,
    DegradedModeSignal,
    ProfileConfig,
    validate,
    with_degraded_fallback,
)


def test_validate_accepts_skip_auth_for_local_profile():
    validate(ProfileConfig(profile="local", skip_auth=True))


def test_validate_accepts_safe_non_local_without_skip_auth():
    validate(ProfileConfig(profile="saas", skip_auth=False))


def test_validate_rejects_skip_auth_outside_local():
    with pytest.raises(ConfigValidationError, match="skip_auth is only permitted"):
        validate(ProfileConfig(profile="saas", skip_auth=True))


@pytest.mark.parametrize("profile", ["standalone", "kubernetes", "outposts"])
def test_validate_rejects_skip_auth_for_each_deployed_profile(profile):
    with pytest.raises(ConfigValidationError):
        validate(ProfileConfig(profile=profile, skip_auth=True))


def test_with_degraded_fallback_uses_primary_when_available():
    signal = DegradedModeSignal()

    result = with_degraded_fallback(lambda: "secrets-manager", lambda: "ssm", signal)

    assert result == "secrets-manager"
    assert signal.degraded_mode is False


def test_with_degraded_fallback_uses_alt_and_emits_signal_on_primary_failure():
    signal = DegradedModeSignal()

    def primary():
        raise RuntimeError("secrets manager unavailable")

    result = with_degraded_fallback(primary, lambda: "ssm", signal)

    assert result == "ssm"
    assert signal.degraded_mode is True


def test_with_degraded_fallback_does_not_swallow_programming_errors():
    signal = DegradedModeSignal()

    def primary():
        raise TypeError("bad kwargs — a bug, not a dependency outage")

    with pytest.raises(TypeError):
        with_degraded_fallback(primary, lambda: "ssm", signal)
    assert signal.degraded_mode is False


def test_with_degraded_fallback_propagates_when_both_paths_fail():
    signal = DegradedModeSignal()

    def primary():
        raise RuntimeError("primary down")

    def alt():
        raise RuntimeError("alt down too")

    with pytest.raises(RuntimeError, match="alt down too"):
        with_degraded_fallback(primary, alt, signal)
    assert signal.degraded_mode is True
