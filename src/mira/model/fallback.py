"""Fallback chain and circuit breaker for the model gateway (ADR-011)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from mira.providers.protocols import ILLMProvider


class FallbackError(Exception):
    pass


class RetryableProviderError(FallbackError):
    pass


class ThrottleError(FallbackError):
    pass


class BudgetExceededError(FallbackError):
    pass


class ContextOverflowError(FallbackError):
    pass


class CircuitOpenError(FallbackError):
    pass


class FallbackExhaustedError(FallbackError):
    pass


_DOWNGRADE = (ThrottleError, BudgetExceededError, ContextOverflowError)


@dataclass(frozen=True)
class ProviderSlot:
    name: str
    provider: ILLMProvider
    model: str | None = None


@dataclass
class FallbackPolicy:
    max_retries: int = 2
    retry_backoff_seconds: float = 0.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float | None = None
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 60.0

    def backoff_for_attempt(self, attempt: int) -> float:
        """Exponential backoff for retry ``attempt`` (0-based), per ADR-011 §1.

        Returns ``retry_backoff_seconds * backoff_multiplier ** attempt``, capped
        at ``max_backoff_seconds`` when set. A zero base delay (the default) keeps
        retries instantaneous so tests and dev runs do not sleep.
        """
        if self.retry_backoff_seconds <= 0:
            return 0.0
        delay = self.retry_backoff_seconds * (self.backoff_multiplier ** attempt)
        if self.max_backoff_seconds is not None:
            delay = min(delay, self.max_backoff_seconds)
        return delay


class _BreakerState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._clock = clock or time.monotonic
        self._state = _BreakerState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False

    @property
    def state(self) -> str:
        return self._state

    def allow(self) -> bool:
        if self._state is _BreakerState.CLOSED:
            return True
        if self._state is _BreakerState.OPEN:
            if self._opened_at is None:
                return False
            if self._clock() - self._opened_at >= self._recovery_timeout:
                self._state = _BreakerState.HALF_OPEN
                self._half_open_probe_in_flight = True
                return True
            return False
        # HALF_OPEN: admit only a single probe until it succeeds or fails.
        if self._half_open_probe_in_flight:
            return False
        self._half_open_probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = _BreakerState.CLOSED
        self._opened_at = None
        self._half_open_probe_in_flight = False

    def record_failure(self) -> None:
        if self._state is _BreakerState.HALF_OPEN:
            self._trip()
            return
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = _BreakerState.OPEN
        self._opened_at = self._clock()
        self._failure_count = 0
        self._half_open_probe_in_flight = False


@dataclass
class FallbackChain:
    primary: ProviderSlot
    fallbacks: Sequence[ProviderSlot] = ()
    downgrade: ProviderSlot | None = None
    policy: FallbackPolicy = field(default_factory=FallbackPolicy)
    cache: Mapping[str, str] | None = None
    manual_response: str | None = None

    def __post_init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        try:
            return self._retry_primary(prompt, model=model)
        except _DOWNGRADE:
            return self._downgrade(prompt, model=model)
        except RetryableProviderError:
            pass
        for slot in self.fallbacks:
            try:
                return self._call_with_breaker(slot, prompt, model=model)
            except _DOWNGRADE:
                return self._downgrade(prompt, model=model)
            except (RetryableProviderError, CircuitOpenError):
                continue
        if self.cache is not None and prompt in self.cache:
            return self.cache[prompt]
        if self.manual_response is not None:
            return self.manual_response
        raise FallbackExhaustedError("all fallback strategies exhausted")

    def breaker_for(self, slot_name: str) -> CircuitBreaker:
        if slot_name not in self._breakers:
            self._breakers[slot_name] = CircuitBreaker(
                failure_threshold=self.policy.failure_threshold,
                recovery_timeout_seconds=self.policy.recovery_timeout_seconds,
            )
        return self._breakers[slot_name]

    def _retry_primary(self, prompt: str, *, model: str | None) -> str:
        breaker = self.breaker_for(self.primary.name)
        if not breaker.allow():
            raise RetryableProviderError(f"circuit open for {self.primary.name}")
        last_error: RetryableProviderError | None = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                result = self._invoke(self.primary, prompt, model=model)
                breaker.record_success()
                return result
            except _DOWNGRADE:
                breaker.record_failure()
                raise
            except RetryableProviderError as exc:
                breaker.record_failure()
                last_error = exc
                if attempt < self.policy.max_retries:
                    delay = self.policy.backoff_for_attempt(attempt)
                    if delay > 0:
                        time.sleep(delay)
        raise last_error or RetryableProviderError("primary retries exhausted")

    def _call_with_breaker(self, slot: ProviderSlot, prompt: str, *, model: str | None) -> str:
        breaker = self.breaker_for(slot.name)
        if not breaker.allow():
            raise CircuitOpenError(f"circuit open for {slot.name}")
        try:
            result = self._invoke(slot, prompt, model=model)
        except _DOWNGRADE:
            breaker.record_failure()
            raise
        except RetryableProviderError:
            breaker.record_failure()
            raise
        breaker.record_success()
        return result

    def _downgrade(self, prompt: str, *, model: str | None) -> str:
        if self.downgrade is None:
            raise FallbackExhaustedError("downgrade requested but no downgrade slot configured")
        return self._invoke(self.downgrade, prompt, model=model)

    def _invoke(self, slot: ProviderSlot, prompt: str, *, model: str | None) -> str:
        return slot.provider.complete(prompt, model=model if model is not None else slot.model)
