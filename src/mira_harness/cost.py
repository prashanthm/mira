"""LLM cost attribution ledger and cost-anomaly detection (ADR-042).

Extracted to the agent-agnostic harness plane (ADR-050);
``mira.model.cost_attribution`` re-exports from here. In the reference agent,
``mira.model.routing`` emits one ``CostLatencySpan`` per completed model call
(via ``Router.record_call`` and the ADR-010 gateway) and ``cost_spans.py`` maps
those observations onto OpenTelemetry spans; this module maps *any* span-like
object carrying ``provider``/``model``/``cost``/``latency_ms`` (the
:class:`CostSpanLike` Protocol — routing spans and foreign ``CostRecord``
values alike) onto an in-memory attribution ledger so cost can be sliced by
tenant, domain, tool, model, and provider, and thresholded for the ADR-044
incident workflow.

Everything here is deterministic and clock-free: spans carry their own data,
budget caps and rate baselines are passed in explicitly, and no wall clock or
randomness is consulted. OTel export of ledger aggregates is deferred — the
per-call OTel path already exists in ``cost_spans.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class CostSpanLike(Protocol):
    """Anything carrying the four cost-span attributes (duck-typed, ADR-050:
    severs the dependency on the reference agent's routing module)."""

    provider: str
    model: str
    cost: float
    latency_ms: float

AttributionDimension = Literal["tenant", "domain", "tool", "model", "provider"]

AnomalyKind = Literal["cost_ceiling", "budget_cap", "call_rate_spike"]


@dataclass(frozen=True, slots=True)
class AttributedSpan:
    """A :class:`CostSpanLike` observation enriched with attribution dimensions.

    ``provider``/``model``/``cost``/``latency_ms`` mirror the source span;
    ``tenant``/``domain``/``tool`` are the ADR-042 attribution axes and
    ``correlation_id`` ties the span back to the originating request
    (ADR-040 vocabulary). Unattributed axes default to ``""``.
    """

    provider: str
    model: str
    cost: float
    latency_ms: float
    tenant: str = ""
    domain: str = ""
    tool: str = ""
    correlation_id: str = ""

    @classmethod
    def from_span(
        cls,
        span: CostSpanLike,
        *,
        tenant: str = "",
        domain: str = "",
        tool: str = "",
        correlation_id: str = "",
    ) -> AttributedSpan:
        """Wrap any span-like observation with attribution dimensions."""
        return cls(
            provider=span.provider,
            model=span.model,
            cost=span.cost,
            latency_ms=span.latency_ms,
            tenant=tenant,
            domain=domain,
            tool=tool,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True, slots=True)
class CostTotal:
    """Aggregate for one dimension value: total cost, call count, mean latency.

    ``CostLatencySpan`` carries no token count, so the aggregate is
    cost + calls + mean latency rather than token totals.
    """

    cost: float
    calls: int
    mean_latency_ms: float


class CostLedger:
    """In-memory per-dimension cost aggregation over attributed spans.

    Deterministic and clock-free: spans carry their own data, so the ledger
    needs no injected clock. Aggregation windows are event-based — callers
    slice :attr:`spans` themselves (e.g. for :class:`AnomalyDetector`).
    """

    def __init__(self) -> None:
        self._spans: list[AttributedSpan] = []

    def record(self, span: AttributedSpan) -> None:
        """Append one attributed span to the ledger."""
        self._spans.append(span)

    @property
    def spans(self) -> tuple[AttributedSpan, ...]:
        """All recorded spans, in record order (read-only view)."""
        return tuple(self._spans)

    def totals(self, by: AttributionDimension) -> dict[str, CostTotal]:
        """Aggregate cost/calls/mean-latency keyed by the given dimension."""
        cost: dict[str, float] = {}
        calls: dict[str, int] = {}
        latency_sum: dict[str, float] = {}
        for span in self._spans:
            key = getattr(span, by)
            cost[key] = cost.get(key, 0.0) + span.cost
            calls[key] = calls.get(key, 0) + 1
            latency_sum[key] = latency_sum.get(key, 0.0) + span.latency_ms
        return {
            key: CostTotal(
                cost=cost[key],
                calls=calls[key],
                mean_latency_ms=latency_sum[key] / calls[key],
            )
            for key in cost
        }

    def total_cost(self) -> float:
        """Overall cost across every recorded span."""
        return sum(span.cost for span in self._spans)


# The dims resolver returns the attribution values for the *current* call.
# Recognized keys: tenant, domain, tool, correlation_id; extras are ignored.
DimsResolver = Callable[[], Mapping[str, str]]


class LedgerSpanObserver:
    """A ``SpanObserver``-shaped observer that records into a ledger.

    Attaches to the reference agent's ADR-010 gateway / ADR-011 router exactly
    like its OTel span observer. Attribution dimensions
    come from an injected ``dims`` resolver so gateway wiring can bind
    request-scoped tenant/domain/tool/correlation values without this module
    knowing about request context.
    """

    def __init__(self, ledger: CostLedger, *, dims: DimsResolver | None = None) -> None:
        self._ledger = ledger
        self._dims = dims

    def emit(self, span: CostSpanLike) -> None:
        """Wrap the span with current attribution dims and record it."""
        dims = dict(self._dims()) if self._dims is not None else {}
        self._ledger.record(
            AttributedSpan.from_span(
                span,
                tenant=dims.get("tenant", ""),
                domain=dims.get("domain", ""),
                tool=dims.get("tool", ""),
                correlation_id=dims.get("correlation_id", ""),
            )
        )


@dataclass(frozen=True, slots=True)
class Anomaly:
    """One threshold breach detected over a span window.

    ``dimension`` names what breached (e.g. ``"span"`` for a single-span
    ceiling, ``"tenant:acme"`` for a budget cap, ``"window"`` for a rate
    spike); ``observed`` and ``limit`` carry the numbers for alert text.
    """

    kind: AnomalyKind
    dimension: str
    observed: float
    limit: float
    detail: str


class AnomalyDetector:
    """Pure threshold detector over a window of attributed spans (ADR-042).

    Three rules, all explicit-threshold (no learned baseline, no clock):

    - ``cost_ceiling``: any single span's cost exceeds ``span_cost_ceiling``
      (a runaway loop or misrouted model shows up first as a cost signature).
    - ``budget_cap``: a dimension value's cumulative cost over the window
      exceeds its cap from ``budget_caps`` (keyed by ``(dimension, value)``,
      mirroring ADR-011 budget-cap scoping).
    - ``call_rate_spike``: the window's span count exceeds
      ``spike_factor × baseline_count`` — the baseline is passed explicitly
      by the caller (e.g. the previous window's count), never derived from
      an internal clock.
    """

    def __init__(
        self,
        *,
        span_cost_ceiling: float | None = None,
        budget_caps: Mapping[tuple[AttributionDimension, str], float] | None = None,
        spike_factor: float = 3.0,
    ) -> None:
        if spike_factor <= 0:
            raise ValueError(f"spike_factor must be positive, got {spike_factor}")
        self._span_cost_ceiling = span_cost_ceiling
        self._budget_caps = dict(budget_caps or {})
        self._spike_factor = spike_factor

    def check(
        self,
        window: Sequence[AttributedSpan],
        *,
        baseline_count: int | None = None,
    ) -> list[Anomaly]:
        """Evaluate all rules over the window; strictly-below thresholds pass."""
        anomalies: list[Anomaly] = []

        if self._span_cost_ceiling is not None:
            for span in window:
                if span.cost > self._span_cost_ceiling:
                    anomalies.append(
                        Anomaly(
                            kind="cost_ceiling",
                            dimension="span",
                            observed=span.cost,
                            limit=self._span_cost_ceiling,
                            detail=(
                                f"single-span cost {span.cost} exceeds ceiling "
                                f"{self._span_cost_ceiling} "
                                f"(provider={span.provider}, model={span.model}, "
                                f"correlation_id={span.correlation_id})"
                            ),
                        )
                    )

        for (dimension, value), cap in self._budget_caps.items():
            cumulative = sum(
                span.cost for span in window if getattr(span, dimension) == value
            )
            if cumulative > cap:
                anomalies.append(
                    Anomaly(
                        kind="budget_cap",
                        dimension=f"{dimension}:{value}",
                        observed=cumulative,
                        limit=cap,
                        detail=(
                            f"cumulative cost {cumulative} for {dimension}={value!r} "
                            f"exceeds budget cap {cap}"
                        ),
                    )
                )

        if baseline_count is not None:
            threshold = self._spike_factor * baseline_count
            if len(window) > threshold:
                anomalies.append(
                    Anomaly(
                        kind="call_rate_spike",
                        dimension="window",
                        observed=float(len(window)),
                        limit=threshold,
                        detail=(
                            f"window call count {len(window)} exceeds "
                            f"{self._spike_factor} x baseline {baseline_count}"
                        ),
                    )
                )

        return anomalies


__all__ = [
    "Anomaly",
    "CostSpanLike",
    "AnomalyDetector",
    "AnomalyKind",
    "AttributedSpan",
    "AttributionDimension",
    "CostLedger",
    "CostTotal",
    "DimsResolver",
    "LedgerSpanObserver",
]
