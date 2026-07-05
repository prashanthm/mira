# ADR-042: AgentOps Telemetry & LLM Cost Attribution

## Status

Accepted

## Context

Mira inherits a fixed telemetry stack — Prometheus metrics and OpenTelemetry/OTLP tracing at the
MCP tool boundary — and extends it rather than replacing it. What the inherited stack cannot see
is the economics of the agent layer: which tenant, domain, and tool consumed which model spend.
The [ADR-010](./adr-010-provider-agnostic-model-gateway.md) gateway already emits one
`CostLatencySpan` (provider, model, cost, latency) per completed model call through the
`SpanObserver` seam in `model/routing.py`, and `model/cost_spans.py` maps those observations onto
OTel spans with `gen_ai.*` / `mira.*` attributes. What was missing is the attribution layer above
the raw spans: per-dimension cost aggregation, and threshold-based anomaly signals for the
[ADR-044](./adr-044-incident-detection-and-remediation.md) incident workflow. Because it is
cross-cutting, this ADR also fixes the AgentOps vocabulary the rest of Phase E depends on:
[ADR-043](./adr-043-slos-and-error-budgets.md)'s SLOs consume these measurements, and ADR-044's
detection rules fire on the anomalies this layer surfaces.

## Decision Drivers

1. **Attribution axes** — cost must slice by tenant, domain, tool, model, and provider without
   changing the gateway call path.
2. **One seam, many sinks** — attribution attaches through the existing `SpanObserver` Protocol,
   exactly like the OTel observer; the gateway stays sink-agnostic.
3. **Determinism** — no wall clock, no randomness: spans carry their own data, thresholds and
   baselines are passed explicitly, so tests and replays are exact.
4. **Feed ADR-043/ADR-044** — the ledger is the substrate SLIs and anomaly detection read from.
5. **Core-dependency discipline** — no new dependencies; OTel remains injected, never imported.

## Decision

Adopt an **in-memory attribution ledger behind the existing span-observer seam**, implemented in
`src/mira/model/cost_attribution.py`:

**1. `AttributedSpan`** — a frozen dataclass carrying the `CostLatencySpan` fields (provider,
model, cost, latency_ms) plus the attribution dimensions: `tenant`, `domain`, `tool` (optional,
default `""`) and `correlation_id` tying the span to its originating request (ADR-040
vocabulary). `AttributedSpan.from_span(...)` wraps a routing span.

**2. `CostLedger`** — deterministic in-memory aggregation: `record(span)` appends;
`totals(by=...)` aggregates cost, call count, and mean latency (`CostTotal`, frozen) keyed by any
of the five dimensions; `total_cost()` gives the overall figure. `CostLatencySpan` carries no
token count, so aggregates are cost + calls + mean latency. Windows are event-based — callers
slice `ledger.spans` themselves.

**3. `LedgerSpanObserver`** — implements the `SpanObserver` Protocol so it attaches to the
gateway/router exactly like `OtelSpanObserver`. Attribution values come from an injected
`dims: Callable[[], Mapping[str, str]]` resolver, so gateway wiring binds request-scoped
tenant/domain/tool/correlation values without this module knowing about request context.

**4. `AnomalyDetector`** — a pure threshold detector over a window of attributed spans, emitting
frozen `Anomaly(kind, dimension, observed, limit, detail)` records for three rules:

| Rule | Trigger | Rationale |
|------|---------|-----------|
| `cost_ceiling` | one span's cost > absolute ceiling | a runaway loop or misrouted model shows up first as a cost signature |
| `budget_cap` | a dimension value's cumulative window cost > its cap (`(dimension, value) → cap` dict, mirroring ADR-011 scoping) | hard spending limit blown |
| `call_rate_spike` | window count > `spike_factor × baseline_count`, baseline passed explicitly | traffic anomaly without an internal clock |

All thresholds are exclusive (exactly-at-limit is not an anomaly), preventing false positives at
the boundary. Anomalies feed `IncidentDetector.from_anomalies` (ADR-044).

**Rejected alternatives:**

- **Aggregate inside the OTel pipeline only** — Rejected: makes attribution depend on an exporter
  and a metrics backend; the reference implementation must be testable offline and deterministic.
- **Extend `BudgetTracker` (ADR-011) into the attribution store** — Rejected: the tracker is a
  routing *gate* (pre-call enforcement); attribution is post-call *accounting* across more axes.
  Keeping them separate preserves each one's single responsibility.
- **Attribute via new gateway/`record_call` parameters** — Rejected: would grow the gateway API
  for every new dimension; the injected dims resolver keeps the seam stable.

## Consequences

### Becomes Easier

- Per-tenant/domain/tool/model/provider cost answers come from one ledger call.
- Anomaly detection and SLO measurement have a deterministic, offline-testable substrate.
- Any number of observers (OTel + ledger + future sinks) attach at the same gateway seam.

### Becomes Harder

- The in-memory ledger is per-process and unbounded; production deployments need periodic
  draining or an exporter (deferred below).
- Correct attribution depends on the dims resolver being wired per request — an unwired resolver
  silently aggregates under `""`.

### Deferred

- **OTel exporter wiring for the ledger** — per-call OTel spans exist (`cost_spans.py`); exporting
  ledger *aggregates* as metrics is deferred.
- **Wall-clock windowing** — windows are event-count slices supplied by the caller; calendar
  windows (and pricing-table versioning as providers change prices) are deferred.
- **Dashboards / alert-manager integration** — the ledger and detector expose the data; dashboard
  and alert-manager plumbing is deployment-specific and deferred.

## Applies To

- **MIRA-RUNTIME** — model gateway telemetry (primary)
- [ADR-010](./adr-010-provider-agnostic-model-gateway.md) / [ADR-011](./adr-011-model-fallback-cost-routing.md) — span emission seam and budget-cap vocabulary this builds on
- [ADR-043](./adr-043-slos-and-error-budgets.md) — SLIs measured over this telemetry
- [ADR-044](./adr-044-incident-detection-and-remediation.md) — anomalies feed incident detection
- [ADR-040](./adr-040-decision-trace-audit.md) — `correlation_id` vocabulary

## Links

- ADR file: `docs/adr/adr-042-agentops-telemetry-and-llm-cost-attribution.md`
- Implementation: `src/mira/model/cost_attribution.py`, `src/mira/model/cost_spans.py`
- Tests: `tests/test_cost_attribution.py`, `tests/test_cost_spans.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-042
- Epic: MIRA-RUNTIME
