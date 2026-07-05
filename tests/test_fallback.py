"""Unit tests for fallback chain and circuit breaker (ADR-011)."""

from __future__ import annotations

import pytest

from mira.model.fallback import (
    BudgetExceededError,
    CircuitBreaker,
    CircuitOpenError,
    ContextOverflowError,
    FallbackChain,
    FallbackExhaustedError,
    FallbackPolicy,
    ProviderSlot,
    RetryableProviderError,
    ThrottleError,
)


class ScriptingProvider:
    def __init__(self, script: list[Exception | str]) -> None:
        self._script = list(script)
        self.calls = 0

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        self.calls += 1
        if not self._script:
            return f"ok:{prompt}"
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def embed(self, text: str) -> list[float]:
        return [1.0]


def _slot(name: str, script: list[Exception | str]) -> ProviderSlot:
    return ProviderSlot(name=name, provider=ScriptingProvider(script))


def test_retry_then_fallback_on_primary() -> None:
    primary = _slot("primary", [RetryableProviderError("500"), RetryableProviderError("500"), "ok"])
    chain = FallbackChain(primary=primary, policy=FallbackPolicy(max_retries=2))
    assert chain.complete("hello") == "ok" and primary.provider.calls == 3


def test_provider_rotation_on_5xx() -> None:
    chain = FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")]),
        fallbacks=[_slot("fallback", ["fallback-ok"])],
        policy=FallbackPolicy(max_retries=0),
    )
    assert chain.complete("rotate") == "fallback-ok"


def test_primary_retry_exhaustion_rotates_to_fallback() -> None:
    # Primary fails every attempt across its full retry budget, then the chain
    # must rotate to the fallback provider (covers retry-exhaustion -> rotation).
    max_retries = 2
    primary = _slot("primary", [RetryableProviderError("500")] * (max_retries + 1))
    fallback = _slot("fallback", ["fallback-ok"])
    chain = FallbackChain(
        primary=primary,
        fallbacks=[fallback],
        policy=FallbackPolicy(max_retries=max_retries),
    )
    assert chain.complete("rotate-after-exhaustion") == "fallback-ok"
    assert primary.provider.calls == max_retries + 1
    assert fallback.provider.calls == 1


@pytest.mark.parametrize("error", [ThrottleError("429"), BudgetExceededError("cap"), ContextOverflowError("x")])
def test_model_downgrade_signals(error: Exception) -> None:
    chain = FallbackChain(
        primary=_slot("primary", [error]),
        downgrade=_slot("cheap", ["downgraded"]),
        policy=FallbackPolicy(max_retries=0),
    )
    assert chain.complete("prompt") == "downgraded"


def test_downgrade_without_slot_raises_exhausted() -> None:
    chain = FallbackChain(
        primary=_slot("primary", [ThrottleError("429")]),
        policy=FallbackPolicy(max_retries=0),
    )
    with pytest.raises(FallbackExhaustedError):
        chain.complete("no-downgrade-slot")


def test_exponential_backoff_grows_per_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = FallbackPolicy(
        max_retries=3,
        retry_backoff_seconds=0.5,
        backoff_multiplier=2.0,
        max_backoff_seconds=2.0,
    )
    # Base * multiplier**attempt, capped: 0.5, 1.0, 2.0, then capped at 2.0.
    assert [policy.backoff_for_attempt(n) for n in range(4)] == [0.5, 1.0, 2.0, 2.0]

    sleeps: list[float] = []
    monkeypatch.setattr("mira.model.fallback.time.sleep", sleeps.append)
    chain = FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")] * (policy.max_retries + 1)),
        policy=policy,
    )
    # Primary exhausts its retry budget; with no fallback the chain is exhausted.
    with pytest.raises(FallbackExhaustedError):
        chain.complete("exhaust")
    # One sleep per retry gap (max_retries), with exponential growth then cap.
    assert sleeps == [0.5, 1.0, 2.0]


def test_cache_and_manual_last_resorts() -> None:
    policy = FallbackPolicy(max_retries=0)
    assert FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")]),
        fallbacks=[_slot("fallback", [RetryableProviderError("503")])],
        cache={"cached-key": "cached-value"},
        policy=policy,
    ).complete("cached-key") == "cached-value"
    assert FallbackChain(
        primary=_slot("p2", [RetryableProviderError("500")]),
        manual_response="manual-degraded",
        policy=policy,
    ).complete("no-cache") == "manual-degraded"
    with pytest.raises(FallbackExhaustedError):
        FallbackChain(primary=_slot("p3", [RetryableProviderError("500")]), policy=policy).complete("fail")


def test_circuit_breaker_trip_half_open_and_reset() -> None:
    now = {"t": 0.0}
    b = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=lambda: now["t"])
    b.record_failure()
    assert b.state == "open" and not b.allow()
    now["t"] = 10.0
    assert b.allow() and b.state == "half_open"
    b.record_success()
    assert b.state == "closed"
    b.record_failure()
    now["t"] = 20.0
    assert b.allow()
    b.record_failure()
    assert b.state == "open"


def test_half_open_admits_single_probe() -> None:
    now = {"t": 0.0}
    b = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=lambda: now["t"])
    b.record_failure()
    now["t"] = 10.0
    # First call after the window admits the probe; concurrent/subsequent calls
    # are rejected until the probe resolves (standard breaker pattern).
    assert b.allow() and b.state == "half_open"
    assert not b.allow()
    b.record_success()
    assert b.state == "closed" and b.allow()


def test_fallback_chain_skips_open_circuit_provider() -> None:
    dead, healthy = _slot("dead", [RetryableProviderError("503")]), _slot("healthy", ["healthy-ok"])
    chain = FallbackChain(
        primary=_slot("primary", [RetryableProviderError("500")]),
        fallbacks=[dead, healthy],
        policy=FallbackPolicy(max_retries=0, failure_threshold=1),
    )
    chain.breaker_for("dead").record_failure()
    with pytest.raises(CircuitOpenError):
        chain._call_with_breaker(dead, "blocked", model=None)
    assert chain.complete("use-healthy") == "healthy-ok"
    assert dead.provider.calls == 0 and healthy.provider.calls == 1
