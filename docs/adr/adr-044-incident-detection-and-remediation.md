# ADR-044: Incident Detection & Remediation Workflow

## Status

Accepted

## Context

Production incidents in an agent platform have shapes traditional alerting misses: a runaway
retrieval loop that burns cost budget before any latency alarm fires, a tenant blowing through a
spending cap, or a quality regression that shows up as SLO burn rather than error rate. Phase E
now provides the signals — [ADR-042](./adr-042-agentops-telemetry-and-llm-cost-attribution.md)'s
cost anomalies and [ADR-043](./adr-043-slos-and-error-budgets.md)'s `SloStatus` — and Phase D
provides the delivery seam ([ADR-039](./adr-039-hitl-escalation.md)'s `WebhookNotifier` with
injectable transport and clock). What was open: how signals become incidents with a severity, how
incidents are routed, and which remediation levers apply — automatically or with a human in the
loop.

## Decision Drivers

1. **Reuse the ADR-039 seam** — one notification mechanism for escalations and incidents; no
   second webhook stack.
2. **Deterministic and offline-testable** — injected clock, injected transport, sequence-derived
   ids.
3. **Human-gated remediation** — the platform has code-deploy-free levers (ADR-011 caps, ADR-012
   kill switch, ADR-046 circuit breaker); throwing them automatically on a detector's say-so is a
   bigger risk than the incidents themselves at this maturity.
4. **Auditable** — every routed incident is retained in an append-only history.

## Decision

Adopt a **detector → router pipeline with advisory-only remediation**, implemented in
`src/mira/core/incidents.py`:

**1. `Incident`** — frozen dataclass: `incident_id` (caller-supplied or sequence-derived
`INC-n`), `kind`, `severity ∈ {info, warning, critical}`, `source` (e.g. `cost_anomaly`,
`slo_burn`), a `detail` dict describing the blast radius in agent terms, and `created_at` from
the detector's injected clock — no wall-clock default.

**2. `IncidentDetector`** — maps Phase-E signals to incidents:

- `from_anomalies(anomalies)` — one incident per ADR-042 anomaly. A `budget_cap` breach means a
  hard spending limit is already blown → **critical**; a `cost_ceiling` hit or `call_rate_spike`
  is an early signature needing a human look → **warning**.
- `from_slo(status)` — healthy → `None`; unhealthy → **warning**; error budget fully exhausted
  (`error_budget_remaining_ratio == 0`) → **critical**.

**3. `IncidentRouter`** — dispatches through exactly one configured path: the Phase-D
`WebhookNotifier` (or any duck-typed notifier with `.notify(decision, context)`) or a plain
`transport: Callable[[dict], None]`. Severity maps onto the ADR-039 escalation vocabulary —
critical → `hold_for_approval` (tier `high`), warning → `notify` (tier `medium`), info →
`proceed` (tier `low`) — so a critical incident produces an escalation-shaped payload that the
existing HITL machinery understands. The router keeps an append-only `history` (exposed as a
tuple).

**4. Remediation advisories** — `remediation_for(incident)` maps kinds to the documented
code-deploy-free lever, attached to the routed payload as a string:

| Incident kind | Advisory lever |
|---------------|----------------|
| `budget_cap` | tighten ADR-011 routing budget caps; ADR-012 kill switch if a prompt/tool version drives the spend |
| `cost_ceiling` | review call path against ADR-011 caps; ADR-012 kill switch on misrouting |
| `call_rate_spike` | engage the ADR-046 circuit breaker to shed load |
| `slo_burn` | roll back the latest promotion via the ADR-012 kill switch |

Advisories are **never auto-executed** — critical incidents hold for a human decision
(`hold_for_approval`); automatic remediation execution is deferred.

**Rejected alternatives:**

- **Automatic remediation on high-confidence detections** — Rejected for now: a false-positive
  kill switch or provider exclusion is itself an incident; the levers stay human-thrown until
  detection precision is proven in production (deferred, with auditing requirements).
- **A separate incident notification channel** — Rejected: ADR-039 already selected the webhook
  mechanism; two delivery stacks means two failure modes and split audit trails.
- **Alerting solely via Prometheus alert-manager rules** — Rejected as the reference semantics:
  detection logic would live in deployment config, untestable offline; alert-manager can mirror
  these rules (deferred integration).

## Consequences

### Becomes Easier

- Cost anomalies and SLO burn reach on-call through the same audited seam as HITL escalations.
- Severity and action mappings are code, unit-tested, and reviewable.
- Every incident carries its advisory remediation, so the runbook step is in the page itself.
- The append-only history gives post-incident review a local record.

### Becomes Harder

- A human is always in the loop for critical incidents — slower reaction than auto-remediation.
- Alert fatigue control (dedup, cooldowns, grouping) is not yet built; noisy thresholds page
  noisily.
- The history is per-process memory; durable incident storage is an integration concern.

### Deferred

- **Automatic remediation execution** — including the audit trail for machine-thrown levers.
- **Alert-manager / on-call-rota integration** — paging schedules, dedup, and grouping live in
  deployment tooling.
- **Learned baselines** — detection stays explicit-threshold (ADR-042) until production data
  justifies statistical baselining.
- **Durable incident store** — history is in-memory; persistence composes with ADR-021 storage
  when required.

## Applies To

- **MIRA-RUNTIME** — AgentOps incident workflow (primary)
- [ADR-042](./adr-042-agentops-telemetry-and-llm-cost-attribution.md) / [ADR-043](./adr-043-slos-and-error-budgets.md) — signal sources
- [ADR-039](./adr-039-hitl-escalation.md) — notification seam and escalation vocabulary
- [ADR-011](./adr-011-model-fallback-cost-routing.md) / [ADR-012](./adr-012-prompt-tool-versioning.md) / [ADR-046](./adr-046-agent-layer-resilience.md) — the advisory remediation levers

## Links

- ADR file: `docs/adr/adr-044-incident-detection-and-remediation.md`
- Implementation: `src/mira/core/incidents.py`
- Tests: `tests/test_incidents.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-044
- Epic: MIRA-RUNTIME
