# ADR-014: Domain-Agent & Supervisor Routing Model

## Status

Accepted

## Context

The product brief commits MIRA-AGENTS to "right specialist per query — research, finance
+ supervisor." This ADR decides the **multi-agent topology**: how work is decomposed into domain
specialists and routed. It sits **above** the per-agent reasoning loop ([ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md)
— "supervisor routing sits above this per-agent loop") and is built on the agent framework
([ADR-007](./adr-007-core-agent-stack-and-framework.md) — LangGraph, chosen partly for explicit
multi-agent control). Specialists are discoverable via agent cards ([ADR-035](./adr-list.md)) and are
clean per-agent identity boundaries ([ADR-034](./adr-list.md)).

## Decision Drivers

1. **MIRA-AGENTS** — the right domain specialist per query; research/finance + a supervisor.
2. **Auditable, regulated setting** — routing needs a single, traceable control flow (NIST / OWASP LLM06).
3. **ADR-007 (LangGraph)** — subgraphs isolate per-agent state; supervisor is a first-class pattern.
4. **Identity & least-privilege (ADR-034/035)** — a specialist is a natural identity + scope boundary.
5. **Cost discipline** — multi-agent has real token overhead; specialize only where it pays.

## Research & Rubric

`Research & rubric — ADR-014`. Scored supervisor (orchestrator-worker) on LangGraph subgraphs vs swarm (peer hand-off) vs a monolithic single agent against the committed pattern, right-specialist routing, auditable control flow, governance/bounding, LangGraph fit, identity boundaries, and cost. The supervisor model wins — it is the committed and dominant production pattern, the only one with a single auditable control flow, and a documented effective shape for enterprise-data discovery. Self-contained on 2026 multi-agent-orchestration practice + a peer-reviewed domain-assistant precedent + NIST/OWASP; internal ADRs fix the framework and integration points.

## Decision

Adopt a **supervisor (orchestrator-worker) routing model with domain specialists, built on LangGraph
subgraphs.**

**1. Topology**
- A **supervisor agent** classifies each request and **routes to the right domain specialist(s)** —
  the `research` specialist (over the Markdown docs connector: `docs.search`/`docs.sections`) and the
  `finance` specialist (over the CSV ledger connector: `ledger.query`/`ledger.categories`); an
  `analytics` specialist is a natural future addition — then collects and **synthesizes** the result.
- Each **specialist is a LangGraph subgraph** running the [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md)
  reasoning loop with **isolated state**; specialists do not share working memory.
- Default to routing to a **single specialist**; fan out to several only when the task genuinely
  needs parallelism or cross-domain critique (cost discipline).

**2. Discovery & identity**
- Specialists are **discoverable via agent cards** ([ADR-035](./adr-list.md)) — the routing/interop
  contract — so the supervisor (and later dynamic composition, [ADR-015](./adr-list.md)) selects from
  declared capabilities rather than hard-wiring.
- Each specialist is a **per-agent identity / least-privilege boundary** ([ADR-034](./adr-list.md)):
  it exercises only the entitlements its domain task needs.

**3. Bounds & failure boundaries**
- **Hierarchical failure boundaries:** keep the agent count modest; introduce team subgraphs before
  the combinatorial-failure threshold (~8 agents). The supervisor defines what happens when a
  specialist fails or loops — retry, reroute, or **escalate to HITL** ([ADR-039](./adr-list.md)).
- **Cap supervisor↔specialist round-trips** (routing accuracy degrades as history crowds out task
  state); interacts with ADR-013 loop bounds and ADR-017 memory compression.

**4. Containment & observability**
- All routing is **LangGraph in the orchestration layer** ([ADR-007](./adr-007-core-agent-stack-and-framework.md)
  containment); model calls go through the gateway ([ADR-010](./adr-list.md)), tools through MCP.
- Routing decisions, hand-offs, and synthesis emit plan/`tool_call` events ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md))
  and OTel spans, with cost attributed per specialist (ADR-042).

**Rejected alternatives:**

- **Swarm (peer hand-off, no supervisor)** — Rejected: no central control flow to audit or bound;
  harder to govern/debug in a regulated setting; doesn't match the committed supervisor pattern.
- **Monolithic single agent (no decomposition)** — Rejected: no specialization, an over-broad
  prompt/tool/identity surface, poor governance separation; fails "right specialist per query."
- **Static if/else routing (no agentic supervisor)** — Rejected: brittle as domains/skills grow;
  agent-card-driven routing scales with the discoverable set (ADR-035/015).

## Consequences

### Becomes Easier

- The right domain specialist handles each query; new domains are added as workers/cards.
- A single supervisor control flow is auditable and debuggable — fits the regulated setting.
- Each specialist is a clean identity/least-privilege and state-isolation boundary.
- Composes with dynamic workflow composition (ADR-015) and scaffolding (ADR-016).

### Becomes Harder

- Multi-agent token overhead is real — route to one specialist by default; fan-out must be justified.
- Routing accuracy and reliability need round-trip caps + hierarchical failure boundaries as agents grow.
- Supervisor quality (classification/synthesis) becomes load-bearing; it needs its own evals (ADR-045).

## Applies To

- **MIRA-AGENTS** — domain agents + supervisor (primary)
- **MIRA-REASON** — supervisor routing sits above the reasoning loop
- **MIRA-COMPOSE** — dynamic composition builds on this routing
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — LangGraph subgraphs / containment
- [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) — the per-agent loop each specialist runs
- [ADR-034](./adr-list.md) / [ADR-035](./adr-list.md) — per-agent identity & agent-card discovery
- [ADR-015](./adr-list.md) (composition) / [ADR-016](./adr-list.md) (scaffolding) / [ADR-039](./adr-list.md) (HITL on failure)

## Links

- ADR file: `docs/adr/adr-014-domain-agent-supervisor-routing.md`
- Research & rubric: `research/adr-014-domain-agent-supervisor-routing.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-014
- Epic: MIRA-AGENTS
