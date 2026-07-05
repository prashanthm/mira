# ADR-009: Middleware Pipeline Architecture

## Status

Accepted

## Context

[ADR-033](./adr-033-phase-1-minimum-identity-slice.md) (Accepted) established the Phase-1 request
chokepoint — inbound JWT validation, per-request attribution (tenant/user/correlation), MCP token
relay, service identity. Phase 1 implemented these as concrete steps; the initiative needs them
generalized into a **single composable pipeline** that is the one place every cross-cutting
concern — auth, correlation, guardrails, telemetry — is enforced, for every agent request.

This sits under the [ADR-007](./adr-007-core-agent-stack-and-framework.md) contract: the agent runtime
is LangGraph, and per the **containment rule** enforcement must **not** live inside framework
internals — the pipeline wraps LangGraph execution rather than implementing concerns as graph nodes.
It references the [ADR-002](./adr-002-provider-abstraction-pattern.md) `IObservability` seam and the
inherited MCP-server ADR-011/ADR-012 telemetry, and defines where the [ADR-037 (Proposed)](./adr-037-bidirectional-guardrail-pipeline.md)
guardrails plug in.

## Decision Drivers

1. **Single enforced chokepoint** — every request passes the same ordered chain; no concern is
   bypassable (NIST AI RMF oversight/measurement).
2. **Guardrail boundary** — input and output need an explicit, controlled boundary (OWASP LLM01/LLM02).
3. **ADR-007 containment** — enforcement must be framework-agnostic, wrapping the LangGraph graph,
   not coupled to it.
4. **Generalize ADR-033** — the Phase-1 validate→attribute→relay steps become ordered middleware.
5. **Observability binding** — correlation/trace context bound once at the boundary and propagated
   (OpenTelemetry).

## Research & Rubric

Research & rubric: `research/adr-009-middleware-pipeline-architecture.md`. Scored a composable ordered middleware chain vs a monolithic handler vs framework-internal hooks against chokepoint enforcement, guardrail boundary, testability/reorderability, ADR-007 containment, and generalizing ADR-033. The composable chain wins decisively — it is the standard ASGI web-boundary pattern, gives guardrails an explicit in/out boundary, and wraps LangGraph without coupling enforcement to it. Evidence is self-contained on ASGI/Starlette, OWASP LLM Top 10, NIST AI RMF, and OpenTelemetry; internal ADRs supply the concrete stage list.

## Decision

Adopt a **composable, ordered middleware pipeline** as the single per-request enforcement chokepoint
for the Agent API. The pipeline wraps LangGraph execution; each stage is an independently-testable
middleware that may short-circuit.

**Canonical stage order (request → response, onion model):**

```
inbound:  auth/JWT validation → correlation/attribution bind → entitlement context
          → guardrail-IN
   core:  → [ LangGraph graph execution (ADR-007) — MCP tool calls relay caller token ]
outbound: → guardrail-OUT → telemetry/audit emit → response
```

- **Auth (first):** validate `Authorization: Bearer` per ADR-033 / the inherited MCP-server ADR-007 (JWT validation approach); fail closed; no stage runs before auth.
- **Correlation/attribution:** bind `tenant_id`/`user_id`/`correlation_id` to structlog + OTel span once ([ADR-033](./adr-033-phase-1-minimum-identity-slice.md), inherited MCP-server ADR-012); never regenerate a valid correlation id.
- **Entitlement context:** carry the caller context the MCP relay forwards (enforcement owned by the inherited MCP-server ADR-022; Phase-2 task-scope narrowing by [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md)).
- **Guardrail-IN / -OUT:** the boundary where [ADR-037 (Proposed)](./adr-037-bidirectional-guardrail-pipeline.md) input/output guardrails run; *where*, not *what* (ADR-037 owns the design). Output guardrails run before the response leaves, including on `error` and on LangGraph `interrupt()` (HITL) paths, and per-chunk for SSE/WebSocket streams ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)).
- **Telemetry/audit (last):** emit the structured/OTLP record ([ADR-002](./adr-002-provider-abstraction-pattern.md) `IObservability`, inherited MCP-server ADR-013); decision-trace hooks for ADR-040 (Proposed; see [adr-list.md](./adr-list.md)) / [ADR-045 (Proposed)](./adr-045-eval-framework-ci-safety-gate.md).

**Containment:** the pipeline is framework-agnostic ASGI/Starlette middleware; LangGraph is invoked
as the innermost handler. No middleware imports `langchain*`/`langgraph*` ([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment rule).

**Idempotency across pause/resume:** when the graph pauses on `interrupt()` and later resumes, the
request still exits through guardrail-OUT/telemetry on pause and re-enters the chain on resume;
middleware must be safe to run across both.

**Rejected alternatives:**

- **Monolithic request handler** — Rejected: stages not independently testable/reorderable;
  guardrail + telemetry tangle with orchestration; defeats the chokepoint's maintainability intent.
- **Framework-internal hooks (LangGraph nodes/callbacks)** — Rejected: couples auth/guardrails to
  LangGraph, violating the ADR-007 containment rule and making the security boundary framework-specific.
- **Per-route ad-hoc checks** — Rejected: no single chokepoint; concerns become bypassable as routes grow.

## Consequences

### Becomes Easier

- One ordered chain to reason about; each concern is one testable middleware.
- Guardrails (ADR-037) and decision-trace/eval hooks (ADR-040/045) have a defined insertion point.
- Correlation/trace bound once and propagated; audit is uniform across every request.
- Enforcement stays framework-agnostic — survives a framework change (ADR-007 fallback).

### Becomes Harder

- Stage ordering is a correctness invariant (auth first; guardrail-OUT before any response exit) —
  must be tested, including error and `interrupt()` paths.
- Streaming output guardrails require per-chunk handling, more complex than buffered responses.
- Middleware must be idempotent across LangGraph pause/resume.

## Applies To

- **MIRA-ARCH** — middleware pipeline (primary)
- **MIRA-RUNTIME** — Agent API request lifecycle
- **MIRA-SAFETY** — guardrail insertion boundary
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — conforms to the containment + contract
- [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — Phase-1 chokepoint this generalizes
- [ADR-037 (Proposed)](./adr-037-bidirectional-guardrail-pipeline.md) — guardrails that plug into guardrail-IN/-OUT
- [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) — streaming the pipeline must support
- Inherited: MCP-server ADR-011 (structured logging) / ADR-012 (correlation ID propagation) / ADR-013 (metrics & tracing)

## Links

- ADR file: `docs/adr/adr-009-middleware-pipeline-architecture.md`
- Research & rubric: `research/adr-009-middleware-pipeline-architecture.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-009
