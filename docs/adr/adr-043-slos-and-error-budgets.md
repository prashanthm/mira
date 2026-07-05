# ADR-043: SLOs & Error Budgets

## Status

Accepted

## Context

An agent surface fails differently from a CRUD API: a request can be slow because the reasoning
loop legitimately took more steps, expensive because retrieval widened, or "successful" at the
HTTP layer while the answer failed a quality check. Without committed objectives, operability is
argued anecdotally and every regression becomes a debate. The catalog commits to SLOs and error
budgets across latency, cost, and error rate; the concrete indicators, targets, accounting
windows, and where they surface were open. The measurement substrate exists —
[ADR-042](./adr-042-agentops-telemetry-and-llm-cost-attribution.md)'s telemetry and the
[ADR-008](./adr-008-runtime-persistence-warm-start.md) warm service's health endpoints — and the
burn *policy* hand-off target is the [ADR-044](./adr-044-incident-detection-and-remediation.md)
incident workflow.

## Decision Drivers

1. **SLOs-as-code** — objectives live next to the service (reviewable, versioned), not in a
   dashboard config that drifts.
2. **Determinism** — accounting must be reproducible offline: no wall clock in the tracking path.
3. **Liveness discipline** — SLO burn must be *visible* at the health surface but must never flip
   liveness; a burning budget pages, it does not restart pods.
4. **Clean hand-off** — the tracker measures; ADR-044 decides what a burn does.

## Decision

Adopt **event-count SLO tracking as code**, implemented in `src/mira/config/slos.py` and surfaced
through the ADR-008 warm service:

**1. `Slo`** — frozen dataclass: `name`, `description`, `objective` (a ratio in `(0, 1]`), and
`window_events` — the accounting window is the last N events, not a calendar interval, so
tracking is deterministic and clock-free.

**2. `SloTracker`** — a per-SLO ring buffer (`deque(maxlen=window_events)`) of good/bad outcomes.
`record(name, good)` appends (the oldest event slides out); `status(name)` returns a frozen
`SloStatus` with `good`, `total`, `achieved_ratio`, `error_budget_total = (1-objective) × total`,
`error_budget_spent` (bad count), `error_budget_remaining_ratio` clamped to `[0, 1]`, and
`healthy = achieved_ratio ≥ objective`. Zero recorded events is vacuously healthy — no events is
no evidence of burn.

**3. `DEFAULT_SLOS`** — the reference service's objectives as code:

| SLO | Objective | Window | SLI (good event) |
|-----|-----------|--------|------------------|
| `turn-success` | 0.99 | 1000 turns | turn completed without error or hard guardrail block |
| `turn-latency-under-budget` | 0.95 | 1000 turns | turn finished within its ADR-013 latency budget (ratio-of-good-events, so the event window stays deterministic) |
| `eval-gate-pass` | 0.99 | 100 runs | an ADR-045 eval-gate execution passed — quality regressions burn budget before user-visible errors |

**4. Health surfacing** — `slo_health_payload(tracker)` renders a JSON-safe per-SLO summary; the
`WarmService` accepts an optional `slo_tracker` and, when configured, includes it under an
`"slos"` key in the `/health` liveness body. Liveness status stays `"ok"` regardless of SLO
health (burn pages via ADR-044, it must not flap the liveness probe), `/health/ready` is
untouched, and the no-tracker response is byte-identical to before.

**Rejected alternatives:**

- **Prometheus recording rules as the SLO source of truth** — Rejected: objectives would live in
  deployment config, untestable offline and invisible to code review; the tracker is the
  reference semantics, exporters can mirror it.
- **Wall-clock (rolling 28-day) windows** — Rejected for the reference implementation: brings the
  wall clock into core logic; event-count windows give identical math with exact tests (calendar
  windowing deferred).
- **A dedicated `/slo` endpoint** — Rejected: the health surface already exists and is scraped;
  one more route adds API surface without new capability.
- **Failing readiness on SLO burn** — Rejected: turns a quality signal into an availability
  outage; burn handling belongs to the ADR-044 escalation path.

## Consequences

### Becomes Easier

- Regressions are measured against committed objectives instead of argued anecdotally.
- SLO math is exact and unit-tested, including the edge cases (empty window, at-objective,
  exhausted budget, `objective = 1.0`).
- ADR-044 consumes a single frozen `SloStatus` shape to decide severity.
- Operators see budget state on the endpoint they already scrape.

### Becomes Harder

- Callers must classify and `record` each event; an unwired tracker reads as vacuously healthy.
- Event-count windows differ from the calendar windows most SLO tooling reports; mapping to
  30-day dashboards needs the deferred exporter.
- With this accounting, an unhealthy window has by definition exhausted its budget — burn-*rate*
  (fast/slow) alerting needs the deferred multi-window support.

### Deferred

- **Wall-clock windowing** and multi-window burn-rate alerts (fast burn vs. slow burn).
- **Exporter integration** — mirroring `SloStatus` into Prometheus/alert-manager.
- **Quality SLOs beyond the eval gate** (guardrail-block rate, unsupported-claim rate from
  ADR-038, escalation rate from ADR-039) — remain diagnostics for now.
- **Per-tenant budget scoping** — the reference tracker is per-service; multi-tenant scoping
  composes with ADR-042 attribution when needed.

## Applies To

- **MIRA-RUNTIME** — service operability (primary)
- [ADR-008](./adr-008-runtime-persistence-warm-start.md) — `/health` surfacing on the warm service
- [ADR-042](./adr-042-agentops-telemetry-and-llm-cost-attribution.md) — measurement substrate
- [ADR-044](./adr-044-incident-detection-and-remediation.md) — burn policy and escalation
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — the eval-gate SLI

## Links

- ADR file: `docs/adr/adr-043-slos-and-error-budgets.md`
- Implementation: `src/mira/config/slos.py`, `src/mira/core/service.py`
- Tests: `tests/test_slos.py`, `tests/test_health_slos.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-043
- Epic: MIRA-RUNTIME
