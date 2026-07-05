"""Concrete OTel-backed cost/latency span observer (ADR-042).

`routing.py` defines the :class:`~mira.model.routing.SpanObserver` Protocol and a
:class:`~mira.model.routing.CostLatencySpan` shape, and calls ``record_call`` to
emit one observation per model call. This module provides a concrete observer
that maps that observation onto an OpenTelemetry span.

To keep business logic free of a hard OpenTelemetry SDK dependency (consistent
with the injectable seams elsewhere in ``mira.core``), the tracer is injected via
the :class:`Tracer` Protocol below. Production code passes a real
``opentelemetry.trace.Tracer`` (whose ``start_as_current_span`` / span API match
this Protocol); tests pass a fake tracer and assert on the recorded attributes.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from mira.model.routing import CostLatencySpan

# Span name and attribute keys. The ``gen_ai.*`` keys follow OpenTelemetry's
# GenAI semantic conventions so spans line up with standard dashboards; the
# ``mira.*`` keys carry the cost/latency attribution this task is about.
SPAN_NAME = "mira.model.call"
ATTR_PROVIDER = "gen_ai.system"
ATTR_MODEL = "gen_ai.request.model"
ATTR_COST = "mira.model.cost"
ATTR_LATENCY_MS = "mira.model.latency_ms"


@runtime_checkable
class Span(Protocol):
    """The slice of the OTel span API this observer uses."""

    def set_attribute(self, key: str, value: object) -> None:
        """Set a single attribute on the span."""


@runtime_checkable
class Tracer(Protocol):
    """Injectable tracer seam — matches OTel's ``Tracer.start_as_current_span``.

    ``start_as_current_span`` returns a context manager yielding a :class:`Span`,
    so the span is entered and exited (and thus ended/exported) around the
    attribute writes.
    """

    def start_as_current_span(self, name: str) -> AbstractContextManager[Span]:
        """Start a span and enter it as the current span."""


class OtelSpanObserver:
    """A :class:`~mira.model.routing.SpanObserver` backed by an OTel tracer.

    Each call to :meth:`emit` opens one span named :data:`SPAN_NAME` and records
    the provider, model, cost, and latency of the observed model call as span
    attributes.
    """

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def emit(self, span: CostLatencySpan) -> None:
        """Record ``span`` as an OTel span with cost/latency attributes."""
        with self._tracer.start_as_current_span(SPAN_NAME) as otel_span:
            otel_span.set_attribute(ATTR_PROVIDER, span.provider)
            otel_span.set_attribute(ATTR_MODEL, span.model)
            otel_span.set_attribute(ATTR_COST, span.cost)
            otel_span.set_attribute(ATTR_LATENCY_MS, span.latency_ms)
