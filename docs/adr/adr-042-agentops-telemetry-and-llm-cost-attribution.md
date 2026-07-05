# ADR-042: AgentOps Telemetry & LLM Cost Attribution

Status: Proposed

## Context

Mira inherits a fixed telemetry stack — Prometheus metrics and OpenTelemetry/OTLP tracing at the
MCP tool boundary — and extends it rather than replacing it. What the inherited stack cannot see
is the economics of the agent layer: which tenant, agent, workflow step, and prompt version
consumed which model tokens at what cost. The ADR-010 gateway already emits token/cost spans via
`model/cost_spans.py`, and ADR-011 routes on cost signals, but there is no committed design for
the span schema, the cost model, or the operational surfaces built on top of them.

The open questions are the span/cost-model design and the AgentOps layer above it. Span design:
which attributes every model-call span must carry (tenant, user, agent, task, prompt version per
ADR-012, fallback-chain position per ADR-011, retrieval-loop round per ADR-029) so cost can be
sliced along any of those axes; how per-token pricing tables are versioned as providers change
prices; and how costs aggregate from span → request → session → tenant. Operational layer: cost
dashboards, budget alerting tied to ADR-011 budget caps, and anomaly detection (a runaway loop or
a misrouted model shows up first as a cost signature) feeding the ADR-044 incident workflow.

Because it is cross-cutting, this ADR also fixes the AgentOps vocabulary the rest of Phase E
depends on: ADR-043's SLOs need these measurements as their SLIs, and ADR-044's detection rules
fire on the anomalies this telemetry surfaces.

## Decision (pending)

This ADR will select the LLM cost-attribution span schema, the cost model and its aggregation
rules, and the dashboards/alerting/anomaly-detection built on the inherited OpenTelemetry stack.
It builds directly on `model/cost_spans.py` — the existing token/cost-span emission seam in the
ADR-010 model gateway — and on the ADR-009 telemetry middleware stage for request-level roll-up;
it extends, and must remain compatible with, the inherited Prometheus/OTLP conventions.

Planned phase: E (AgentOps, with ADR-043 and ADR-044).
