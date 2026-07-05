"""Agent-layer resilience for MCP client calls (ADR-046)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ResilienceError(Exception):
    """Base error for agent-layer resilience failures."""


class CircuitOpenError(ResilienceError):
    """Raised when the circuit breaker is open and calls are rejected."""


class MCPCallError(ResilienceError):
    """Raised when an MCP client call fails after retries."""


class MCPTimeoutError(MCPCallError):
    """Raised when an MCP client call exceeds its timeout."""


class CircuitBreaker:
    """Simple circuit breaker for agent↔MCP-client calls."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._clock = clock or time.monotonic
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.OPEN:
                return False
            if self._state == CircuitState.HALF_OPEN:
                # Single-probe gate: permit only one trial call while half-open so
                # concurrent callers don't storm a recovering dependency.
                if self._half_open_probe_in_flight:
                    return False
                self._half_open_probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None
            self._half_open_probe_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()
            self._half_open_probe_in_flight = False

    def _maybe_transition_to_half_open(self) -> None:
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return
        if self._clock() - self._opened_at >= self.reset_timeout:
            self._state = CircuitState.HALF_OPEN
            self._failure_count = 0
            self._half_open_probe_in_flight = False


@dataclass(frozen=True, slots=True)
class DegradedResult:
    """Partial answer with an explicit caveat for traceability."""

    value: Any
    reason: str
    caveat: str
    partial: bool = True


def degrade(
    partial: Any,
    reason: str,
    *,
    escalate: Callable[[str], None] | None = None,
    should_escalate: bool = False,
) -> DegradedResult:
    """Return a caveated partial result or escalate when degradation is insufficient."""
    if should_escalate:
        if escalate is None:
            raise ResilienceError(f"Escalation required: {reason}")
        escalate(reason)
        raise ResilienceError(f"Escalated: {reason}")
    caveat = f"Partial result: {reason}"
    return DegradedResult(value=partial, reason=reason, caveat=caveat, partial=True)


class Bulkhead:
    """Concurrency isolation so one failing component cannot exhaust all capacity."""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._semaphore = threading.Semaphore(max_concurrent)

    def run(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            raise ResilienceError("Bulkhead capacity exhausted")
        try:
            return fn(*args, **kwargs)
        finally:
            self._semaphore.release()


def _default_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (MCPTimeoutError, TimeoutError, ConnectionError, OSError))


def call_mcp(
    client: Callable[[Any], Any],
    req: Any,
    *,
    timeout: float = 30.0,
    retries: int = 3,
    breaker: CircuitBreaker | None = None,
    retryable: Callable[[BaseException], bool] | None = None,
    backoff_base: float = 0.05,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Call an MCP client with timeout, bounded retry/backoff, and optional circuit breaker."""
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    is_retryable = retryable or _default_retryable
    monotonic = clock or time.monotonic
    attempts = retries + 1
    last_error: Exception | None = None

    for attempt in range(attempts):
        if breaker is not None and not breaker.allow_request():
            raise CircuitOpenError("Circuit breaker is open")

        try:
            result = _invoke_with_timeout(client, req, timeout=timeout)
        except Exception as exc:
            # Catch Exception (not BaseException): KeyboardInterrupt/SystemExit
            # must propagate so operator cancellation isn't retried as a call error.
            last_error = exc
            if breaker is not None:
                breaker.record_failure()
            if not is_retryable(exc) or attempt >= attempts - 1:
                if isinstance(exc, FuturesTimeoutError):
                    raise MCPTimeoutError(f"MCP call timed out after {timeout}s") from exc
                if isinstance(exc, ResilienceError):
                    raise
                raise MCPCallError(str(exc)) from exc
            time.sleep(backoff_base * (2**attempt))
            continue

        if breaker is not None:
            breaker.record_success()
        return result

    assert last_error is not None
    raise MCPCallError(str(last_error)) from last_error


def _invoke_with_timeout(client: Callable[[Any], Any], req: Any, *, timeout: float) -> Any:
    # v1 trade-off: a fresh single-worker pool per call keeps timeout handling
    # self-contained at the cost of thread churn. Before this sits on a hot path,
    # swap in a shared executor (follow-up noted in the review).
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client, req)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            raise
