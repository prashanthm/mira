# ADR-013: Reasoning Pattern & Loop-Safety Bounds

## Status

Accepted

## Context

The product brief commits MIRA-REASON to "planner, reflection, loop safety, plan stream" with
"auditable steps; users see what is planned." [ADR-007](./adr-007-core-agent-stack-and-framework.md)
selects LangGraph specifically for explicit, durable, bounded loop control — its graph model and
`recursion_limit` are *why* it was chosen. This ADR fixes the reasoning pattern and, critically, the
**hard bounds** that make the agent loop safe in a regulated setting, where an unbounded
or opaque agent loop is unacceptable (OWASP LLM06 Excessive Agency).

## Decision Drivers

1. **MIRA-REASON** — plan/reflect, loop safety, and a visible plan stream (`plan_step` events, ADR-006).
2. **Tool-heavy, exploratory queries** — cross-source analytical questions need mid-course correction, not a rigid up-front plan.
3. **Hard loop-safety (OWASP LLM06 / NIST AI RMF)** — bounded, observable, interruptible behavior.
4. **ADR-007 (LangGraph)** — express the loop as graph nodes/edges; use `recursion_limit` + `interrupt()`.
5. **ReAct + Reflexion literature** — the committed plan/act/observe/reflect pattern.

## Research & Rubric

`Research & rubric — ADR-013`. Scored ReAct-on-LangGraph-with-hard-bounds vs plan-and-execute vs a free-form autonomous loop against pattern fit, mid-course correction, hard loop-safety bounds, auditable/visible steps, and governance (OWASP LLM06 / NIST). ReAct on LangGraph wins — literature-backed plan/reflect, native graph expression, `recursion_limit` plus layered token/time/cost bounds and `interrupt()` HITL gates. Self-contained on the ReAct/Reflexion papers, LangGraph docs, OWASP LLM Top 10, NIST/MITRE; internal docs supply the commitment.

## Decision

Adopt **ReAct (plan → act → observe → reflect)** as the reasoning pattern, expressed as
**LangGraph nodes/edges**, with **multi-layer hard loop-safety bounds** and `interrupt()` HITL gates.

**Reasoning loop:**

- Plan → act (tool call via MCP) → observe → reflect/critique → continue or finish, as an explicit
  LangGraph graph. Reflection follows Reflexion-style self-critique to catch errors before finishing.
- Each reasoning step emits a `plan_step` event ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)) for visible planning; steps are auditable (decision-trace hooks, [ADR-040 (Proposed)](./adr-list.md)).

**Hard loop-safety bounds (layered — all enforced, conservative defaults, configurable per workflow):**

| Bound | Mechanism |
|-------|-----------|
| **Step count** | LangGraph `recursion_limit` (the built-in stop) |
| **Token budget** | per-run token ceiling enforced at the model gateway ([ADR-010 (Proposed)](./adr-list.md)) |
| **Wall-clock** | per-run time budget on the graph execution |
| **Cost ceiling** | per-run cost cap via gateway cost attribution ([ADR-042 (Proposed)](./adr-list.md)) |
| **High-risk actions** | `interrupt()` HITL gate ([ADR-039 (Proposed)](./adr-list.md) escalation) before irreversible/escalated actions |

- **Token-budget scope:** the per-run token ceiling covers the **full reasoning loop** (plan + act +
  reflect steps combined), not act steps only; reflection model calls are within the budget, not
  outside it.
- **Durable waits ≠ loop iterations:** multi-day pauses are `interrupt()`/durable waits
  ([ADR-007](./adr-007-core-agent-stack-and-framework.md)), which **do not** count against the step
  bound. Step bounds count reasoning iterations; wall-clock excludes time parked on a human.
- **Containment:** the graph/`langchain*` code lives in the orchestration/reasoning layer per the
  ADR-007 containment rule; model calls go through the gateway, tools through MCP.

**Rejected alternatives:**

- **Plan-and-execute (full plan up front, then run)** — Rejected as the default: too rigid for
  exploratory, tool-heavy queries; weak mid-course correction. Retained as an option for narrow,
  well-structured flows.
- **Free-form autonomous loop (model decides when to stop)** — Rejected: unbounded autonomy
  (OWASP LLM06), no deterministic stop, opaque steps — unacceptable for regulated workflows.
- **Single hard bound only (e.g. step count)** — Rejected: a step cap alone misses token/cost/time
  runaways; bounds must be layered.

## Consequences

### Becomes Easier

- The committed plan/reflect pattern maps directly to LangGraph nodes; `recursion_limit` is free.
- Runaway loops are impossible — step, token, time, and cost are all bounded; high-risk actions gate to a human.
- Steps are visible (`plan_step`) and auditable, satisfying the plan-visibility + traceability commitments.

### Becomes Harder

- Bound values need per-workflow tuning; too tight stalls legitimate long reasoning, too loose wastes cost.
  The MIRA-REASON spec must define conservative `recursion_limit` defaults as a **safety floor** so
  per-workflow tuning can raise limits but cannot unintentionally remove the bound entirely.
- Keeping "durable wait" distinct from "loop step" requires care so HITL pauses don't trip the loop bound.
- Reflection adds model calls (cost), itself bounded and attributed.

## Applies To

- **MIRA-REASON** — reasoning engine (primary)
- **MIRA-RUNTIME** — graph executes in the runtime
- **MIRA-SAFETY** — loop bounds + HITL gates as a safety control
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — LangGraph graph + `recursion_limit` + `interrupt()`
- [ADR-010 (Proposed)](./adr-list.md) — token/cost bounds enforced at the gateway
- [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) — `plan_step` events; [ADR-039 (Proposed)](./adr-list.md) — HITL escalation; [ADR-040 (Proposed)](./adr-list.md) — decision traces
- [ADR-014 (Proposed)](./adr-list.md) — supervisor routing sits above this per-agent loop

## Links

- ADR file: `docs/adr/adr-013-reasoning-pattern-and-loop-safety.md`
- Research & rubric: `research/adr-013-reasoning-pattern-and-loop-safety.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-013
