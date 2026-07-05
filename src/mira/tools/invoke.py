"""Tool invocation with idempotency, retry, and timeout (ADR-031).

Phase-1 limitations (tracked as follow-ups, not implemented here):

* **Timeout cancels the future, not the worker thread.** ``_run_call`` raises a
  structured timeout error but the underlying synchronous ``call()`` keeps
  running in its thread until it returns. Under repeated timeouts this can leak
  work; long-running tool bodies need an interruptible/async path before this
  sits on a hot production path.
* **Idempotency key gates retries, it does not dedup.** ``invoke`` requires an
  ``idempotency_key`` before retrying an idempotent tool, but does not yet cache
  results or suppress duplicate execution. Dedup (key -> result cache, or wiring
  the key through to the tool) is deferred to a follow-up so e02-f02 AC #1 is not
  read as complete.
* **A fresh ThreadPoolExecutor per timed call** -- fine for unit scope; replace
  with a shared executor if this moves onto a hot path.
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from typing import TypeVar

from mira.tools.contract import ToolContract

T = TypeVar("T")


class ToolInvokeError(Exception):
    """Structured error when tool invocation fails (timeout, retry exhaustion)."""

    def __init__(self, message: str, *, code: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or []


def _run_call(call: Callable[[], T], timeout_s: float | None) -> T:
    if timeout_s is None:
        return call()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(call)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise ToolInvokeError(
                f"Tool call timed out after {timeout_s}s",
                code="timeout",
                details=[f"timeout_s={timeout_s}"],
            ) from exc


def invoke(
    contract: ToolContract,
    call: Callable[[], T],
    *,
    idempotency_key: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Apply contract timeout and retry policy to a tool call.

    ``retry_policy.max_attempts`` is the **total** number of attempts (initial
    try + retries), not retries-after-first-failure: ``max_attempts=3`` means one
    initial call plus up to two retries.
    """
    policy = contract.retry_policy
    max_attempts = policy.max_attempts if policy else 1
    backoff_s = policy.backoff_s if policy else 0.0
    retryable: tuple[type[BaseException], ...] = policy.retryable_exceptions if policy else ()

    attempt = 0
    while True:
        attempt += 1
        try:
            return _run_call(call, contract.timeout_s)
        except ToolInvokeError:
            raise
        except retryable as exc:
            if not contract.idempotentHint:
                raise
            if not idempotency_key:
                raise ToolInvokeError(
                    f"Idempotent tool {contract.name!r} requires idempotency_key for retry",
                    code="missing_idempotency_key",
                ) from exc
            if attempt >= max_attempts:
                raise ToolInvokeError(
                    f"Retry exhausted for tool {contract.name!r} after {attempt} attempt(s)",
                    code="retry_exhausted",
                    details=[f"max_attempts={max_attempts}"],
                ) from exc
            if backoff_s > 0:
                sleep(backoff_s)
        except Exception:
            raise
