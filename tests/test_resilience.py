import threading
import time

import pytest

from mira.core.resilience import (
    Bulkhead,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    DegradedResult,
    MCPCallError,
    MCPTimeoutError,
    ResilienceError,
    call_mcp,
    degrade,
)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_call_mcp_success():
    result = call_mcp(lambda req: {"echo": req}, {"tool": "get_well"}, timeout=1.0, retries=0)
    assert result == {"echo": {"tool": "get_well"}}


def test_call_mcp_timeout():
    def slow_client(_req):
        time.sleep(0.2)
        return "late"

    with pytest.raises(MCPTimeoutError):
        call_mcp(slow_client, {}, timeout=0.05, retries=0)


def test_call_mcp_retries_with_backoff(monkeypatch):
    attempts = {"count": 0}
    sleeps: list[float] = []

    def flaky_client(_req):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("transient")
        return "ok"

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(time, "sleep", fake_sleep)
    result = call_mcp(flaky_client, {}, timeout=1.0, retries=2, backoff_base=0.1)

    assert result == "ok"
    assert attempts["count"] == 3
    assert sleeps == [0.1, 0.2]


def test_call_mcp_non_retryable_fails_immediately():
    attempts = {"count": 0}

    def bad_client(_req):
        attempts["count"] += 1
        raise ValueError("bad input")

    with pytest.raises(MCPCallError):
        call_mcp(bad_client, {}, timeout=1.0, retries=3)

    assert attempts["count"] == 1


def test_circuit_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout=10.0)
    client = lambda _req: (_ for _ in ()).throw(ConnectionError("down"))  # noqa: E731

    for _ in range(3):
        with pytest.raises(MCPCallError):
            call_mcp(client, {}, timeout=1.0, retries=0, breaker=breaker)

    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        call_mcp(client, {}, timeout=1.0, retries=0, breaker=breaker)


def test_circuit_breaker_recovers_after_reset_timeout():
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=5.0, clock=clock.__call__)
    failures = {"count": 0}

    def client(_req):
        failures["count"] += 1
        if failures["count"] <= 2:
            raise ConnectionError("down")
        return "recovered"

    for _ in range(2):
        with pytest.raises(MCPCallError):
            call_mcp(client, {}, timeout=1.0, retries=0, breaker=breaker)

    clock.advance(5.0)
    result = call_mcp(client, {}, timeout=1.0, retries=0, breaker=breaker, clock=clock.__call__)
    assert result == "recovered"
    assert breaker.state == CircuitState.CLOSED


def test_half_open_permits_single_probe():
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, clock=clock.__call__)
    breaker.record_failure()  # -> OPEN
    assert breaker.state == CircuitState.OPEN

    clock.advance(5.0)  # eligible for HALF_OPEN
    # first caller gets the single probe slot
    assert breaker.allow_request() is True
    # concurrent callers are rejected while the probe is in flight
    assert breaker.allow_request() is False
    assert breaker.allow_request() is False

    breaker.record_success()  # probe succeeded -> CLOSED, slot released
    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow_request() is True


def test_half_open_probe_failure_reopens():
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=5.0, clock=clock.__call__)
    breaker.record_failure()
    clock.advance(5.0)
    assert breaker.allow_request() is True  # probe slot taken
    breaker.record_failure()  # probe failed -> OPEN again, slot released
    assert breaker.state == CircuitState.OPEN


def test_degrade_returns_caveated_partial_result():
    result = degrade({"wells": ["A-1"]}, "log tool unavailable")
    assert isinstance(result, DegradedResult)
    assert result.value == {"wells": ["A-1"]}
    assert result.partial is True
    assert "log tool unavailable" in result.caveat


def test_degrade_escalates_when_requested():
    escalated: list[str] = []

    with pytest.raises(ResilienceError, match="Escalation required"):
        degrade("partial", "critical failure", should_escalate=True)

    with pytest.raises(ResilienceError, match="Escalated"):
        degrade(
            "partial",
            "critical failure",
            should_escalate=True,
            escalate=escalated.append,
        )
    assert escalated == ["critical failure"]


def test_bulkhead_limits_concurrency():
    bulkhead = Bulkhead(max_concurrent=1)
    started = threading.Event()
    release = threading.Event()
    results: list[str] = []

    def work(label: str) -> None:
        results.append(label)

    def blocking_work() -> None:
        started.set()
        release.wait(timeout=1.0)

    holder = threading.Thread(target=lambda: bulkhead.run(blocking_work))
    holder.start()
    assert started.wait(timeout=1.0)

    with pytest.raises(ResilienceError, match="capacity exhausted"):
        bulkhead.run(work, "second")

    release.set()
    holder.join(timeout=1.0)
    assert bulkhead.run(work, "after") is None
    assert results == ["after"]


def test_bulkhead_isolates_failures():
    bulkhead = Bulkhead(max_concurrent=2)

    def fail() -> None:
        raise RuntimeError("component failed")

    with pytest.raises(RuntimeError):
        bulkhead.run(fail)

    assert bulkhead.run(lambda: "ok") == "ok"
