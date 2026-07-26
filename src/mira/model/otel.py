"""OpenTelemetry tracing for Mira — vendor-neutral spans over OTLP, so any
backend (Langfuse, Jaeger, Tempo, a collector) reconstructs a distributed
trace: SPA → Vantage → Mira /turn → each LLM call, under one W3C trace id.

Replaces the Langfuse-specific exporter (model/langfuse_export.py): the LLM
generation span is emitted here as GenAI semantic-convention attributes
(gen_ai.*), and Langfuse — which ingests OTLP — still gets its dashboard /
eval / scoring via the collector.

Opt-in + fail-open: a no-op unless an OTLP endpoint is configured
(OTEL_EXPORTER_OTLP_ENDPOINT or the legacy OTLP_ENDPOINT) AND the SDK is
installed (the [otel] extra). Any failure is swallowed — telemetry must never
break or slow a model call.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger(__name__)

SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "mira")

_TRACER: Any = None
_TRIED = False


def _endpoint() -> str | None:
    """The OTLP endpoint from the SDK-standard env, falling back to Mira's
    legacy OTLP_ENDPOINT knob (config/profiles.py). None → tracing disabled."""
    return (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            or os.environ.get("OTLP_ENDPOINT") or None)


def tracer() -> Any:
    """The lazily-built tracer, or None when unconfigured/unavailable. Cached
    (incl. the None result) so a missing SDK / endpoint is probed once."""
    global _TRACER, _TRIED
    if _TRIED:
        return _TRACER
    _TRIED = True
    if _endpoint() is None:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("mira")
    except Exception:  # noqa: BLE001 — SDK absent / bad config → stay a no-op
        log.info("otel endpoint set but tracer init failed — tracing disabled")
        _TRACER = None
    return _TRACER


def enabled() -> bool:
    return tracer() is not None


def extract_context(headers: dict[str, str] | None) -> Any:
    """W3C trace context from inbound headers (traceparent), so a Mira span
    becomes a CHILD of the SPA/Vantage span. None when disabled or absent."""
    if not headers or tracer() is None:
        return None
    try:
        from opentelemetry.propagate import extract
        return extract({k.lower(): v for k, v in headers.items()})
    except Exception:  # noqa: BLE001
        return None


@contextmanager
def root_span(name: str, *, op: str, correlation_id: str | None = None,
              inbound_headers: dict[str, str] | None = None,
              attributes: dict | None = None) -> Iterator[str]:
    """The ONE entry-point tracing pattern — used identically by every entry
    (HTTP /turn, /analyze, /insights, /playbook, and batch/CLI), so
    user-initiated, system-initiated, and batch work all trace the same way.
    Disparate per-entry tracing is the thing this exists to prevent.

    Opens a root span that becomes a CHILD of an inbound W3C traceparent when
    one is present (distributed trace) and a fresh trace-root otherwise (batch/
    CLI, or no header). Mints a correlation_id (uuid4) when the caller passes
    none, and stacks call_context(op, correlation_id) so every LLM call made
    inside the block is tagged and joins this span. Yields the correlation_id.
    Fail-open: with tracing off it's just the call_context tag + a fresh id.
    """
    import uuid

    from mira.model.gateway import call_context
    corr = correlation_id or str(uuid.uuid4())
    ctx = extract_context(inbound_headers)
    attrs = {"vantage.correlation_id": corr, **(attributes or {})}
    with call_context(op, correlation_id=corr), span(name, context=ctx, attributes=attrs):
        yield corr


@contextmanager
def span(name: str, *, context: Any = None, attributes: dict | None = None) -> Iterator[Any]:
    """A span context manager that's a no-op when tracing is disabled — callers
    use `with span(...)` unconditionally. Records exceptions, never raises."""
    t = tracer()
    if t is None:
        yield None
        return
    try:
        with t.start_as_current_span(name, context=context) as sp:
            if attributes:
                for k, v in attributes.items():
                    if v is not None:
                        sp.set_attribute(k, v)
            yield sp
    except Exception:  # noqa: BLE001 — a tracing failure must not break the call
        yield None


def gen_ai_span(*, op: str | None, agent: str, model: str, provider: str,
                request: str, response: str, usage: dict | None,
                cost_usd: float | None, latency_ms: float,
                correlation_id: str | None, error: str | None) -> None:
    """Emit one LLM call as a GenAI-semconv span (gen_ai.*). Same data + same
    call site as the old Langfuse exporter; backend-agnostic now. Best-effort."""
    t = tracer()
    if t is None:
        return
    try:
        u = usage or {}
        attrs = {
            "gen_ai.operation.name": op or "chat",
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": u.get("prompt_tokens"),
            "gen_ai.usage.output_tokens": u.get("completion_tokens"),
            "gen_ai.usage.total_tokens": u.get("total_tokens"),
            "gen_ai.mira.agent": agent,
            "gen_ai.mira.cost_usd": cost_usd,
            "gen_ai.mira.latency_ms": latency_ms,
            "vantage.correlation_id": correlation_id,
        }
        with t.start_as_current_span(f"gen_ai {op or 'chat'}") as sp:
            for k, v in attrs.items():
                if v is not None:
                    sp.set_attribute(k, v)
            # prompt/response as span events (semconv: content lives in events)
            sp.add_event("gen_ai.content.prompt", {"content": request[:8000]})
            sp.add_event("gen_ai.content.completion", {"content": (response or "")[:8000]})
            if error:
                from opentelemetry.trace import Status, StatusCode
                sp.set_status(Status(StatusCode.ERROR, error))
    except Exception:  # noqa: BLE001
        pass
