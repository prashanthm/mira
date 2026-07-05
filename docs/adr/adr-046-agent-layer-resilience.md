# ADR-046: Agent-Layer Resilience Policy

## Status

Accepted

## Context

Resilience for the Mira agent is decided in several places: the model gateway
([ADR-011](adr-list.md)) owns circuit-breaking/fallback, the reasoning loop ([ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md))
owns loop-safety bounds, the runtime ([ADR-008](./adr-008-runtime-persistence-warm-start.md)) owns
health/graceful-drain, and **MCP→source-platform call-path resilience is owned upstream** (inherited
MCP-server ADR-003, the source-platform HTTP client design). This ADR provides
the **coherent agent-layer resilience policy** — naming the patterns, assigning ownership, and
filling the gaps no other ADR covers — without re-deciding those decisions or the upstream-owned
source-platform path.

## Decision Drivers

1. **Coherent statement** — one place that defines agent-layer resilience + degraded-mode behavior.
2. **Respect ownership** — reference (not re-decide) ADR-011/013/008.
3. **Respect upstream scope-out** — MCP→source-platform resilience is the inherited MCP-server ADR-003.
4. **Fill the gaps** — agent↔MCP-client resilience, partial-failure handling, bulkhead isolation.
5. **Governance (NIST AI RMF)** — resilience + graceful degradation as managed risk.

## Research & Rubric

`Research & rubric — ADR-046`. Scored a composing policy (name patterns, assign ownership, fill gaps) vs re-specifying all resilience here vs no policy against coherence, respecting ownership, respecting the upstream scope-out, filling agent-specific gaps, and avoiding duplication. The composing policy wins — it states the canonical stability patterns and closes the real gaps without re-deciding the gateway/loop/runtime or the upstream source-platform path. Self-contained on resilience-engineering patterns (Nygard / Azure / Google SRE) + NIST; internal ADRs fix ownership and scope.

## Decision

Adopt a **composing agent-layer resilience policy**: state the canonical stability patterns, assign
each to its owning decision, and add only the agent-specific gaps.

**1. Pattern ownership (reference, do not re-decide)**

| Pattern | Owned by |
|---------|----------|
| Model-call circuit-breaking, fallback chain, retry/backoff | [ADR-011](adr-list.md) (gateway) |
| Reasoning-loop bounds (step/token/time/cost), `interrupt()` | [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) |
| Runtime health/readiness, graceful drain | [ADR-008](./adr-008-runtime-persistence-warm-start.md) |
| **MCP→source-platform call-path resilience (circuit breaker, retry, pooling)** | **Inherited MCP-server ADR-003 — explicitly out of scope here** |
| Per-user/per-IP rate limiting (429) | Inherited MCP-server ADR-008 (rate-limiting strategy) — agent treats 429 as a managed signal |

**2. Gaps this ADR fills (agent-layer specific)**
- **Agent↔MCP-client resilience:** the agent's own calls to the MCP tool surface get **timeout +
  bounded retry/backoff + a circuit breaker** so a slow/failing tool doesn't hang the reasoning loop.
  This is distinct from (and must not double-count) the inherited MCP→source-platform resilience (MCP-server ADR-003).
- **Partial-failure handling / graceful degradation:** when a specialist ([ADR-014](adr-list.md)) or a
  tool fails, the agent **degrades to a partial, clearly-caveated answer or escalates** ([ADR-039](adr-list.md))
  — never a silent drop or an unbounded retry. Degraded results are traceable ([ADR-040](adr-list.md)).
- **Bulkhead isolation:** one failing specialist/tool is isolated so it doesn't sink the whole request
  (resource/concurrency isolation between specialists).
- **Degraded-mode behavior** is defined and observable (emits a structured signal feeding
  AgentOps/incident, [ADR-042](adr-list.md)/[ADR-044](adr-list.md)).

**3. Boundaries**
- Framework-agnostic, in the orchestration/runtime layer ([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment).
- This ADR is a **reference + gaps** policy; it must not re-specify the gateway/loop/runtime resilience
  (drift risk) or the upstream source-platform path.

**Rejected alternatives:**

- **Re-specify all resilience here** — Rejected: re-decides ADR-011/013/008 and the upstream-owned
  MCP→source-platform path (inherited MCP-server ADR-003); duplication and drift.
- **No agent-layer policy (ad hoc per-ADR)** — Rejected: leaves agent↔MCP-client failures,
  partial-failure UX, and cross-specialist isolation undefined; no single degraded-mode statement.

## Consequences

### Becomes Easier

- One coherent statement of agent-layer resilience + degraded-mode behavior.
- Agent↔MCP-client failures, partial-failure UX, and specialist isolation are explicitly handled.
- No duplication — gateway/loop/runtime/source-platform resilience stay with their owners.
- Degraded mode is observable and feeds incident/AgentOps.

### Becomes Harder

- The reference/gaps boundary must be policed — easy to drift into re-specifying others' resilience.
- Agent↔MCP-client tuning must not double-count the inherited MCP→source-platform resilience.
- Partial-failure UX (when to degrade vs escalate) needs careful product + safety definition.

## Applies To

- **MIRA-RUNTIME** — agent-layer resilience (primary)
- [ADR-011](adr-list.md) (gateway) / [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) (loop) / [ADR-008](./adr-008-runtime-persistence-warm-start.md) (runtime) — resilience this references
- [ADR-014](adr-list.md) — bulkhead isolation between specialists; [ADR-039](adr-list.md) — escalate on failure
- [ADR-040](adr-list.md) (traceable degraded answers) / [ADR-042](adr-list.md) / [ADR-044](adr-list.md) (incident on sustained failure)
- Inherited: MCP-server ADR-003 (MCP→source-platform — out of scope), MCP-server ADR-008 (429 boundary)

## Links

- ADR file: `docs/adr/adr-046-agent-layer-resilience.md`
- Research & rubric: `research/adr-046-agent-layer-resilience.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-046
- Epic: MIRA-RUNTIME
