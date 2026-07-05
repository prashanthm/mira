# ADR-040: Decision-Trace Audit Model

## Status

Accepted

## Context

Mira's trust story rests on one requirement: every factual claim an agent makes must be traceable
to the source records that support it. The eval gate ([ADR-045](./adr-045-eval-framework-ci-safety-gate.md))
already asserts claim→source linkage in CI, and ADR-025 requires multi-source conflicts to be
surfaced rather than silently resolved — but until Phase D there was no production audit model that
records, retains, and serves those linkages for a live request after it ran.

The requirements that shaped the model: records must be immutable once written (audit integrity),
correlated by the inherited correlation ID ([ADR-033](./adr-033-phase-1-minimum-identity-slice.md))
so they join with the OpenTelemetry trace, cheap to write on the request path, and rich enough to
serve as the system of record for [ADR-041](./adr-041-explanation-api-and-uncertainty.md)'s
`/explain` projections and [ADR-038](./adr-038-hallucination-and-topic-drift-controls.md)/
[ADR-039](./adr-039-hitl-escalation.md) verdicts.

## Decision Drivers

1. **Append-only by construction** — immutability must be structural (frozen records, no
   update/delete surface), not a convention reviewers have to police.
2. **CI schema as the floor** — the ADR-045 trace assertions (plan visibility, claim→source
   grounding) define the minimum the production record must carry.
3. **Deterministic and offline** — no wall-clock or randomness defaults baked in; the clock is
   injected so records are reproducible in tests and evals.
4. **Joinability** — correlation ID on every record; monotonic sequence numbers give a total order
   without trusting timestamps.
5. **Storage behind seams** — the in-memory store is the reference; persistent backends slot in
   behind the same contract (ADR-002/021).

## Decision

Adopt an **append-only decision-trace store with frozen records and claim→source extraction from
specialist results**, implemented in `src/mira/core/decision_trace.py`:

- **`TraceRecord`** (frozen dataclass) — one immutable audit record per request: caller-supplied
  `trace_id`, `correlation_id` (ADR-033), the `query`, a tuple of frozen **`TracedClaim`**s
  (deterministic statement repr plus the `source_id`/`source_type` attribution edge; empty
  attribution marks an ungrounded claim rather than hiding it), the `plan_steps` taken (ADR-013
  plan/act/observe/reflect transitions, carried verbatim), any `guardrail_findings`
  (ADR-036/038 verdicts, ADR-039 decisions), a store-assigned monotonic `sequence`, and
  `created_at` from the injected clock.
- **`TraceStore`** — append-only: `append(...)` assigns the next sequence and returns the frozen
  record; reads are `get(trace_id)`, `for_correlation(correlation_id)`, and `all()`, all returning
  tuples so callers cannot mutate store state. **There is no update or delete method** — the
  absence is asserted by test. The clock is a required constructor injection
  (`TraceStore(clock=…)`); no `time.time` default exists at import.
- **`record_from_result(trace_id, correlation_id, result_dict)`** — the write-path convenience:
  extracts claims from a `SpecialistResult`-shaped dict using the same recursive provenance rule
  as ADR-038/045 (every provenance-carrying node in the answer becomes a claim→source edge; a
  non-empty answer with no attribution becomes a single ungrounded claim), carries plan steps over,
  and appends.
- **Emission point** — per ADR-009, the telemetry stage (or the app layer that owns the pipeline)
  writes the record after guardrail-OUT has run, so recorded findings reflect what the guardrails
  actually saw.

**Rejected alternatives:**

- **Mutable records with an audit log of changes** — Rejected: an audit model whose primary
  records can change needs a second audit model; frozen-by-construction is simpler and stronger.
- **Deriving traces purely from OTel spans** — Rejected: spans are operational telemetry with
  retention and sampling policies unfit for an audit system of record; the decision trace joins
  *to* OTel via the correlation ID instead.
- **Wall-clock default timestamps** — Rejected: bakes nondeterminism into the audit path and
  violates the repo-wide injectable-clock rule.

## Consequences

### Becomes Easier

- ADR-041's `/explain` is a pure read projection over the store — explanations cannot diverge from
  what was recorded.
- ADR-038 findings and ADR-039 escalation decisions have a durable, correlated home.
- Sequence numbers give a trustworthy total order independent of clock quality.

### Becomes Harder

- Claim granularity is structural (one claim per provenance-carrying node); finer-grained
  claim extraction (sentence-level) needs a richer extractor behind the same record shape.
- Callers must supply the trace ID and clock; there is no ambient magic — deliberate, but more
  wiring at the call site.

### Deferred

- **Persistent store backend** (relational/graph per ADR-021) behind the same
  `append`/`get`/`for_correlation` contract, with retention and tenant isolation policy.
- **Redaction of sensitive content inside traces** — statements are reprs of answer content today;
  a redaction pass (ADR-033 conventions) belongs at the persistent boundary.
- Write-path cost controls (sampling/queueing) if trace volume grows.

## Applies To

- **MIRA-SAFETY** — the audit spine for guardrail and escalation verdicts.
- [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — correlation-ID joinability.
- [ADR-038](./adr-038-hallucination-and-topic-drift-controls.md) / [ADR-039](./adr-039-hitl-escalation.md) — producers of recorded findings/decisions.
- [ADR-041](./adr-041-explanation-api-and-uncertainty.md) — the read API over this store.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — CI assertions defining the minimum schema.

## Links

- ADR file: `docs/adr/adr-040-decision-trace-audit.md`
- Implementation: `src/mira/core/decision_trace.py`; tests: `tests/test_decision_trace.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-040
