import time

import pytest

from mira.tools.contract import RetryPolicy, ToolContract
from mira.tools.invoke import ToolInvokeError, invoke


class RetryableError(Exception):
    pass


def _base_contract(**overrides) -> ToolContract:
    defaults = {
        "name": "sample_tool",
        "description": "sample",
        "inputSchema": {"type": "object", "properties": {}},
        # ToolContract is fail-closed on entitlement (authz declaration, #21).
        "required_entitlement": "users.tools.invoke@partition.dataservices.energy",
    }
    defaults.update(overrides)
    return ToolContract(**defaults)


def test_safe_retry_with_idempotency_key():
    contract = _base_contract(
        idempotentHint=True,
        retry_policy=RetryPolicy(
            retryable_exceptions=(RetryableError,),
            max_attempts=3,
            backoff_s=0.0,
        ),
    )
    attempts = {"count": 0}

    def call() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RetryableError("transient")
        return "ok"

    result = invoke(contract, call, idempotency_key="key-1")
    assert result == "ok"
    assert attempts["count"] == 2


def test_invoke_success_without_retry_policy():
    # Default single-attempt path: no retry_policy, no timeout.
    contract = _base_contract()
    calls = {"count": 0}

    def call() -> str:
        calls["count"] += 1
        return "done"

    assert invoke(contract, call) == "done"
    assert calls["count"] == 1


def test_no_retry_for_non_idempotent_tool():
    contract = _base_contract(
        idempotentHint=False,
        retry_policy=RetryPolicy(retryable_exceptions=(RetryableError,), max_attempts=3),
    )
    attempts = {"count": 0}

    def call() -> None:
        attempts["count"] += 1
        raise RetryableError("fail")

    with pytest.raises(RetryableError):
        invoke(contract, call, idempotency_key="key-1")
    assert attempts["count"] == 1


def test_backoff_between_retries():
    contract = _base_contract(
        idempotentHint=True,
        retry_policy=RetryPolicy(
            retryable_exceptions=(RetryableError,),
            max_attempts=3,
            backoff_s=0.05,
        ),
    )
    attempts = {"count": 0}
    sleeps: list[float] = []

    def call() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableError("transient")
        return "ok"

    invoke(contract, call, idempotency_key="key-1", sleep=sleeps.append)
    assert attempts["count"] == 3
    assert sleeps == [0.05, 0.05]


def test_timeout_raises_structured_error():
    contract = _base_contract(timeout_s=0.05)

    def call() -> str:
        time.sleep(0.2)
        return "late"

    with pytest.raises(ToolInvokeError) as exc_info:
        invoke(contract, call)
    assert exc_info.value.code == "timeout"
    assert "timed out" in exc_info.value.message


def test_idempotent_retry_requires_idempotency_key():
    contract = _base_contract(
        idempotentHint=True,
        retry_policy=RetryPolicy(retryable_exceptions=(RetryableError,), max_attempts=3),
    )

    def call() -> None:
        raise RetryableError("fail")

    with pytest.raises(ToolInvokeError) as exc_info:
        invoke(contract, call)
    assert exc_info.value.code == "missing_idempotency_key"


def test_retry_exhaustion_raises_structured_error():
    contract = _base_contract(
        idempotentHint=True,
        retry_policy=RetryPolicy(retryable_exceptions=(RetryableError,), max_attempts=2),
    )

    def call() -> None:
        raise RetryableError("fail")

    with pytest.raises(ToolInvokeError) as exc_info:
        invoke(contract, call, idempotency_key="key-1")
    assert exc_info.value.code == "retry_exhausted"
