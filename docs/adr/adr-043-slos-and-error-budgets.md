# ADR-043: SLOs & Error Budgets

Status: Proposed

## Context

An agent surface fails differently from a CRUD API: a request can be slow because the reasoning
loop legitimately took more steps, expensive because retrieval widened, or "successful" at the
HTTP layer while the answer failed a faithfulness check. Mira needs service-level objectives that
capture this — otherwise operability is argued anecdotally and every regression becomes a debate.
The catalog commits to defining SLOs and error budgets across at least latency, cost, and error
rate as the agent surface's operability target; the concrete indicators, targets, and budget
policy are open.

Open sub-questions: which SLIs to define per surface (interactive chat vs. long-running durable
workflows have different latency semantics — time-to-first-token and stream cadence matter for
one, completion-within-deadline for the other); how cost becomes a first-class SLO (per-request
cost percentiles against budget, using ADR-042's attribution); whether quality signals
(guardrail-block rate, unsupported-claim rate from ADR-038, escalation rate from ADR-039) join
the SLO set or remain diagnostics; and how budgets are scoped (per-tenant, per-agent, or
platform-wide) in a multi-tenant deployment.

Error-budget policy is the enforcement half: what happens when a budget burns — feature freezes,
forced fallback to cheaper/safer configurations via ADR-011 routing and the ADR-012 kill switch,
or paging per ADR-044. Without a committed policy the SLOs are dashboards, not objectives.

## Decision (pending)

This ADR will define the SLI/SLO set for the agent surface (latency, cost, error rate, and any
quality SLOs), the targets, the error-budget accounting windows, and the burn policy. It builds
on ADR-042's telemetry and cost-attribution spans as the measurement substrate (SLIs are queries
over those spans and the inherited Prometheus metrics) and hands its burn-alert thresholds to the
ADR-044 incident workflow.

Planned phase: E (AgentOps, with ADR-042 and ADR-044).
