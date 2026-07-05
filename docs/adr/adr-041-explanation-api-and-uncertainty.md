# ADR-041: Explanation API & Uncertainty Quantification

## Status

Accepted

## Context

[ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) reserved an `/explain`
convention in the agent-facing API standard: for any completed request, a client can ask *why* —
which sources were consulted, which reasoning path was taken, and how confident the system is in
each claim. The design constraint that settled the shape: explanations must be **projections of
the [ADR-040](./adr-040-decision-trace-audit.md) decision trace**, not separately generated
post-hoc narratives, so an explanation can never diverge from what actually happened.

For uncertainty, the honest options are limited: a poorly calibrated probability is worse than a
coarse but truthful signal. What the platform can assert deterministically today is *structural*:
how many of a record's claims carry a claim→source attribution edge, and whether guardrails
flagged the run.

## Decision Drivers

1. **No divergence** — explanations are reads over the audit record; nothing is regenerated.
2. **Honest uncertainty** — expose only signals the platform can actually compute; label them
   structural, not semantic confidence.
3. **Deterministic and offline** — the endpoint and the uncertainty function run with no model
   call on every profile.
4. **ADR-006 conventions** — a plain resource endpoint on the existing warm service, stdlib-only
   (the hand-rolled WSGI surface has no framework to lean on).
5. **Graceful absence** — a deployment without a trace store must say so explicitly, not 404.

## Decision

Adopt a **trace-projection `/explain` endpoint with a deterministic structural uncertainty
summary**, implemented in `src/mira/core/service.py` and `src/mira/core/decision_trace.py`:

- **Endpoint** — `GET /explain` on the ADR-008 warm service (`EXPLAIN_PATH`), query-string parsed
  with stdlib `urllib.parse`:
  - `?trace_id=X` → **200** with the full trace record as JSON — claims with their sources, plan
    steps, guardrail findings, sequence/created_at — or **404** `{"error": "trace_not_found"}`.
  - `?correlation_id=Y` → **200** `{"records": [...]}` — every record for that request, in
    sequence order (a request may produce multiple specialist traces).
  - Neither parameter → **400** `{"error": "missing_parameter"}`.
  - `WarmService` takes an optional `trace_store` constructor parameter; with none configured the
    endpoint answers **503** `{"error": "explanations_unavailable"}` — explicitly absent, not
    missing.
- **Uncertainty** — every served record carries an `"uncertainty"` block from the pure function
  `uncertainty_for(record)`: `grounded_claims`/`total_claims` and their ratio, flags for guardrail
  findings and missing provenance, and a coarse categorical **band** —
  `supported` / `partially_supported` / `unsupported` — derived from claim→source coverage. All
  deterministic, no model call; the band is truthful about being a structural verdict (attribution
  coverage), not a semantic faithfulness score.

**Rejected alternatives:**

- **Post-hoc generated explanation narratives** — Rejected: a second model pass can contradict the
  trace; the summary view, when it lands, must be generated *from* the record and stored with it.
- **Calibrated confidence probabilities** — Rejected for now: no calibration data exists;
  exposing an uncalibrated number misleads. Categorical bands over structural facts are the honest
  floor, with richer signals layered in later (Deferred).
- **A separate explanation service** — Rejected: the warm service already fronts the request
  lifecycle and holds the correlation context; a second surface adds an authorization boundary for
  no gain at this phase.

## Consequences

### Becomes Easier

- Auditors and reviewers read the same record the guardrails wrote — claim-by-claim evidence with
  zero drift from reality.
- Clients get an unambiguous machine-readable signal (`band`, `grounded_ratio`) for rendering
  caveats.
- The endpoint is trivially testable at WSGI level, offline.

### Becomes Harder

- The `uncertainty` block only measures attribution coverage; consumers must not read `supported`
  as "verified true" — the naming and docs say structural, and ADR-038's deferred semantic
  checks are the upgrade path.
- Multi-level views (summary vs. claim-level vs. full trace) are not differentiated yet; today the
  full record is the one view.

### Deferred

- **Entitlement-scoped views** — bounding what a caller may see of a trace (end user vs. reviewer
  vs. auditor) once the authz layer fronts the service (ADR-034).
- **Retrieval-support and check-verdict scores** (ADR-029 critique verdicts, ADR-038 model-graded
  faithfulness) as additional uncertainty inputs behind the same `uncertainty_for` seam.
- **Pre-generated summary views** stored alongside the record at answer time.
- Explanation-view versioning as the trace schema evolves.

## Applies To

- **MIRA-SAFETY** — the trust surface over the Phase-D audit spine.
- [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) — the reserved `/explain` convention this implements.
- [ADR-008](./adr-008-runtime-persistence-warm-start.md) — the warm service the endpoint lives on.
- [ADR-040](./adr-040-decision-trace-audit.md) — the system of record explanations project from.
- [ADR-038](./adr-038-hallucination-and-topic-drift-controls.md) — findings surfaced per record; future faithfulness verdicts feed uncertainty.

## Links

- ADR file: `docs/adr/adr-041-explanation-api-and-uncertainty.md`
- Implementation: `src/mira/core/service.py`, `src/mira/core/decision_trace.py`;
  tests: `tests/test_explain_endpoint.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-041
