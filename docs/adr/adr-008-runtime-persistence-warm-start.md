# ADR-008: Agent Runtime Persistence & Warm-Start Model

## Status

Accepted

## Context

The product brief commits MIRA-RUNTIME to "fast, warm, streaming responses with plan visibility —
persistent runtime, health, WebSocket/streaming." This ADR decides whether the agent runtime is a
**warm persistent process** or **cold per-request invocation**. It builds on already-locked pieces:
the [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) `/health` (liveness) and
`/health/ready` (readiness) endpoints, the durable LangGraph runtime ([ADR-007](./adr-007-core-agent-stack-and-framework.md))
that holds in-flight graph state, provider initialization behind the Protocols
([ADR-002](./adr-002-provider-abstraction-pattern.md)), and the ECS Fargate / EKS placement
([ADR-047](./adr-047-deployment-profiles-and-packaging.md)).

## Decision Drivers

1. **MIRA-RUNTIME** — fast, warm, streaming responses (no per-request init latency).
2. **Streaming + durable state** — the runtime holds streaming connections and LangGraph in-flight state.
3. **Operability (Kubernetes/ECS lifecycle, NIST)** — readiness gating + graceful drain on rollout.
4. **Multi-placement** — fits the ECS Fargate / EKS service model (ADR-047).
5. **ADR-006 probes** — `/health` + `/health/ready` are already specified; this ADR uses them.

## Research & Rubric

Research & rubric: `research/adr-008-runtime-persistence-warm-start.md`. Scored a warm persistent runtime (with probes + graceful shutdown) vs cold per-request invocation vs warm-without-drain against latency, streaming/durable state, readiness gating, graceful drain, placement fit, idle cost, and operability. The warm-persistent model wins — it avoids cold-start latency, hosts streaming + durable state, and follows the standard container-service lifecycle. Self-contained on Kubernetes/12-factor lifecycle practice + NIST; internal ADRs fix the probes and placement.

## Decision

Run the agent runtime as a **warm, persistent service process** with **liveness / readiness /
startup probes** and **graceful shutdown** — not cold per-request invocation.

**1. Warm runtime**
- A long-running service (ECS Fargate task / EKS pod, [ADR-047](./adr-047-deployment-profiles-and-packaging.md))
  initializes providers / MCP client / model+tool warmup **once at startup**, then serves many
  streaming requests — avoiding per-request init latency.
- It is the home for streaming connections (SSE/WebSocket, [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md))
  and the durable LangGraph in-flight state ([ADR-007](./adr-007-core-agent-stack-and-framework.md)).

**2. Health & readiness ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md))**
- **Liveness** (`/health`): process up → restart on failure.
- **Readiness** (`/health/ready`): flips ready **only when providers are initialized and MCP is
  reachable** — traffic is routed only to ready instances. A **startup probe** covers slow warmup.

**3. Graceful shutdown**
- On **SIGTERM**, stop accepting new requests, **drain in-flight** requests/streams within a configured
  window, then exit — so rollouts/scale-down don't drop active streams.
- A **paused (`interrupt()`) multi-day LangGraph run** is **checkpointed** ([ADR-017](./adr-017-memory-architecture.md)) and
  resumes on another instance; it must **not** block the drain window. Define drain-timeout vs
  durable-resume boundary in the spec.

**4. Scaling & profiles**
- Autoscaling with **min replicas ≥ 1** keeps the service warm; per-profile tuning (on-prem may run a
  fixed pool). Autoscaling *signals* (latency/queue depth) are owned by the SLO/observability ADRs
  (ADR-043/ADR-044 — see [adr-list.md](./adr-list.md)).

**Rejected alternatives:**

- **Cold per-request invocation (function-per-request)** — Rejected: per-request cold-start latency
  contradicts "fast, warm"; a poor home for streaming and durable in-flight graph state.
- **Warm process without graceful drain / readiness gating** — Rejected: drops in-flight streams on
  every rollout and serves traffic before dependencies are up; fails the operability bar.
- **Scale-to-zero with pre-warming hacks** — Rejected for Phase 1: complexity without meeting the
  steady-state warmth requirement; revisit only if idle cost proves prohibitive.

## Consequences

### Becomes Easier

- Low first-token latency — providers/MCP/model warmed once, not per request.
- Streaming and durable in-flight LangGraph state have a stable home.
- Rollouts/scale-down don't drop active streams (graceful drain); traffic only hits ready instances.
- Maps directly onto the ECS Fargate / EKS placement.

### Becomes Harder

- Always-on warmth costs more than scale-to-zero (mitigated by right-sized autoscaling).
- Readiness must be honest (only ready when serveable); warmup scope needs tuning.
- The drain window must coexist with durable `interrupt()` runs without blocking shutdown.

## Applies To

- **MIRA-RUNTIME** — persistent runtime & warm-start (primary)
- [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) — `/health`, `/health/ready` probes
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — durable in-flight runtime; [ADR-017](./adr-017-memory-architecture.md) — checkpointer for paused runs
- [ADR-002](./adr-002-provider-abstraction-pattern.md) — provider init at startup
- [ADR-047](./adr-047-deployment-profiles-and-packaging.md) — ECS Fargate / EKS placement; [ADR-048](./adr-048-secure-cloud-runtime-and-network-isolation.md) — Outposts/degraded readiness
- [ADR-046](./adr-046-agent-layer-resilience.md) (runtime resilience) / ADR-043 / ADR-044 (see [adr-list.md](./adr-list.md)) — autoscaling signals & SLOs

## Links

- ADR file: `docs/adr/adr-008-runtime-persistence-warm-start.md`
- Research & rubric: `research/adr-008-runtime-persistence-warm-start.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-008
