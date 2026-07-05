# ADR-040: Decision-Trace Audit Model

Status: Proposed

## Context

Mira's trust story rests on one requirement: every factual claim an agent makes must be traceable
to the source records that support it. The eval gate (ADR-045) already asserts claim→source
linkage over OTLP traces in CI, and ADR-025 requires multi-source conflicts to be surfaced rather
than silently resolved — but there is not yet a production audit model that records, retains, and
serves those linkages for a live request months after it ran.

The current direction is an append-only attribution store: for each request, a decision trace
capturing the reasoning steps taken (plan/act/observe transitions from the ADR-013 loop), the
tool calls and retrieval results consulted (with source identifiers from ADR-028/030 provenance),
the claims in the final answer, and the claim→source edges — immutable once written, correlated by
the inherited correlation ID so it joins with the OpenTelemetry trace. Open sub-questions include
the trace schema and claim-extraction granularity, storage placement (a dedicated store vs. the
ADR-021 relational/graph roles), retention and tenant isolation, redaction of sensitive content
inside traces, and write-path cost — traces must not become the most expensive part of a request.

The decision trace is load-bearing for three siblings: ADR-038's faithfulness checks consume the
claim→source edges at runtime, ADR-039 escalations append approval records to it, and ADR-041's
`/explain` API is largely a read API over it.

## Decision (pending)

This ADR will select the decision-trace schema, the append-only attribution store, and the
write/read contracts. It builds on the ADR-009 telemetry middleware stage as the emission point,
the inherited correlation-ID and OpenTelemetry conventions for joinability, and the ADR-045
trace-based eval suite — the CI assertions define the minimum schema the production store must
satisfy. Storage engines stay behind the ADR-002/021 seams.

Planned phase: D (safety & trust, with ADR-036, ADR-038, ADR-039, ADR-041).
