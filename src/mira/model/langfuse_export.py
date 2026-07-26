"""Langfuse export — ship each LLM call to a self-hosted Langfuse for the live
dashboard, eval datasets, and human/auto scoring (the observability + eval +
fine-tune-corpus tool we chose over a bespoke UI). The durable SQLite
llm_calls/turns store (core/persistence.py) stays the always-on local record;
this is an ADDITIVE second sink.

Opt-in + fail-open: does nothing unless LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
(+ LANGFUSE_HOST) are set AND the SDK is installed. Any export failure is
swallowed — telemetry must never break or slow a model call. Generations are
grouped into one trace by the turn's correlation_id, so a turn's classify +
synthesis calls appear as one trace in the dashboard, matching the SQLite join.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_CLIENT: Any = None
_TRIED = False


def _client() -> Any:
    """The lazily-built Langfuse client, or None when unconfigured/unavailable.
    Cached (incl. the None result) so a missing SDK is probed once, not per call."""
    global _CLIENT, _TRIED
    if _TRIED:
        return _CLIENT
    _TRIED = True
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import get_client
        _CLIENT = get_client()
    except Exception:  # noqa: BLE001 — SDK absent or misconfigured → stay a no-op
        log.info("langfuse configured but client init failed — export disabled")
        _CLIENT = None
    return _CLIENT


def enabled() -> bool:
    return _client() is not None


def export_call(*, op: str | None, agent: str, model: str, provider: str,
                request: str, response: str, usage: dict | None,
                cost_usd: float | None, latency_ms: float,
                correlation_id: str | None, error: str | None) -> None:
    """Record one LLM generation as a Langfuse observation, grouped under the
    turn's correlation_id trace. Best-effort — never raises."""
    client = _client()
    if client is None:
        return
    try:
        u = usage or {}
        kwargs: dict[str, Any] = {
            "as_type": "generation",
            "name": op or "llm-call",
            "model": model,
            "input": request,
        }
        if correlation_id:
            kwargs["trace_id"] = correlation_id
        with client.start_as_current_observation(**kwargs) as gen:
            gen.update(
                output=response,
                usage={"input_tokens": u.get("prompt_tokens"),
                       "output_tokens": u.get("completion_tokens"),
                       **({"cost": cost_usd} if cost_usd is not None else {})},
                metadata={"agent": agent, "provider": provider,
                          "latency_ms": latency_ms, "error": error},
                level="ERROR" if error else "DEFAULT",
            )
    except Exception:  # noqa: BLE001 — telemetry is not the answer path
        pass


def score(correlation_id: str, name: str, value: float,
          comment: str | None = None) -> None:
    """Attach an eval/outcome score to a turn's trace (e.g. a forecast that
    later scored a hit → the reward label for SFT/eval). Best-effort."""
    client = _client()
    if client is None or not correlation_id:
        return
    try:
        client.create_score(trace_id=correlation_id, name=name, value=value,
                             comment=comment)
    except Exception:  # noqa: BLE001
        pass
