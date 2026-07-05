# ADR-007: Core Agent Stack & Framework

## Status

Accepted

## Context

Mira needs an agent framework as the keystone of its agent core: every downstream tool
decision — model gateway, reasoning loop, memory, guardrails, eval — depends on it, and an
eval/guardrail tool coupled to the wrong framework would collide. The catalog recorded "Strands SDK
on Amazon Bedrock is the current direction (subject to ADR)," but **no ADR had compared the field**.

The isolation invariants are already locked and are **referenced, not restated** here:
[ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) fixes the `src/mira/` layout
and the CI lint `no-cloud-sdk-in-business-logic`; [ADR-002](./adr-002-provider-abstraction-pattern.md)
fixes the five Protocol interfaces (`ILLMProvider` … `IObservability`) and the framework seam
("agents call `ILLMProvider`"); [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) fixes the
Phase-1 middleware chokepoint. This ADR decides the framework that runs **behind** those seams, and
sets the contract the dependent tool ADRs conform to.

The decision is grounded in a framework comparison spike and a decided weighting: Mira's target
operational reality is **regulated enterprise workflows with multi-day waits, staged human
decisioning, and deterministic supervisor→specialist routing**, which weights durable, pause/resume,
explicitly-controlled orchestration above isolation convenience.

## Decision Drivers

1. **Durable, human-gated, multi-day orchestration** — workflows pause for days and for humans;
   the framework must persist and resume execution across deploys, not hold blocked threads.
2. **Explicit reasoning-loop control + hard step bounds** — ReAct plan/reflect with enforceable
   step/token limits ([ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) requirement).
3. **Governance fit** — NIST AI RMF, EU AI Act, ISO/IEC 42001 expect human oversight and
   traceability; a durable HITL + state-history substrate satisfies this directly.
4. **Isolation invariants (ADR-001/002)** — the framework must remain swappable behind
   `ILLMProvider`; its types must not leak into business logic.
5. **Open-standard interop** — MCP tool surface (the inherited MCP tool server), A2A agent cards
   ([ADR-035](./adr-035-agent-cards-and-a2a-discovery.md)), OpenTelemetry (inherited MCP-server ADR-013).
6. **Keystone coherence** — dependent tools (gateway, reasoning, memory, guardrails, eval) must have
   a single contract to conform to, decided in order.

## Research & Rubric

Research & rubric: `research/adr-007-core-agent-stack-and-framework.md`. Scored LangGraph vs Strands vs CrewAI (OpenAI Agents SDK rejected for vendor lock-in) under a weighting that favors durable/HITL multi-day orchestration and explicit loop control. LangGraph wins on durable execution (checkpointer + `interrupt()`), `recursion_limit` loop bounds, and governance fit; its one weakness — `langchain-core` leakage past the `/providers/` boundary — is closed by the containment rule below rather than left as a risk. Evidence is self-contained on authoritative LangGraph docs + AI-governance/security standards; internal docs corroborate only. Supersedes the earlier spike's Strands-lead framing.

## Decision

Adopt **LangGraph** as the Mira agent framework, subject to a **containment rule**, and
establish the **tool-coherence contract** and **decision order** for the dependent agent-core ADRs.

**1. Framework: LangGraph**

The agent runtime is built on LangGraph's stateful graph model — agent steps as nodes, transitions
as edges — using its **durable execution** (checkpointer persistence; `interrupt()` for human-pause
and long-wait; resume across deploys) and `recursion_limit` for loop bounds. Models are reached only
through the model gateway ([ADR-010](./adr-010-provider-agnostic-model-gateway.md)) behind `ILLMProvider`; MCP tools via
`langchain-mcp-adapters` in the tool-binding layer.

**2. Containment rule (closes the isolation risk)**

- LangGraph / `langchain*` imports are **confined to the orchestration/runtime layer**
  (`src/mira/runtime/` and the reasoning/graph modules). Business logic, the data fabric, connectors,
  and the Protocol interfaces must **not** import `langchain*`/`langgraph*`.
- Extend the [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) CI lint
  `no-cloud-sdk-in-business-logic` (`ruff`/`import-linter`) to **also forbid `langchain*` and
  `langgraph*` imports outside the designated orchestration layer** — the same mechanism that
  already forbids `boto3`/`azure.*`/`google.cloud.*` outside `providers/`. Implementation lands with
  repo bootstrap (MIRA-PLACE / ADR-004); this ADR records the requirement.
- Rationale: keeps the framework swappable (Strands is the pre-vetted fallback) and preserves the
  ADR-002 seam — agents/business logic depend on `ILLMProvider` and typed tool contracts, not on
  LangChain types.

**3. Tool-coherence contract (every dependent tool ADR must satisfy)**

- **Behind the Protocols** — model access via `ILLMProvider` (ADR-002); state via `IStateStore`;
  observability via `IObservability`. No vendor or framework SDK in business logic.
- **Framework-agnostic eval/telemetry** — evaluation and tracing are **trace/OTLP-based**
  ([ADR-045](./adr-045-eval-framework-ci-safety-gate.md), inherited MCP-server ADR-013), never tied to a framework-specific service (no
  LangSmith), so a framework change does not invalidate evals.
- **Guardrails in the middleware chain** — input/output guardrails plug into the
  [ADR-009](./adr-009-middleware-pipeline-architecture.md) per-request pipeline, not into framework internals.
- **MCP for tools** — agent tools are the inherited MCP tool surface via the adapter layer; tools are
  typed contracts ([ADR-031](./adr-031-typed-tool-contracts.md)), not framework-native bindings.

**4. Decision order (keystone → dependents)**

`ADR-007 → ADR-009 (middleware) → ADR-010 (model gateway) → ADR-013 (reasoning & loop-safety) →
ADR-017 (memory) → ADR-037 (guardrails) → ADR-045 (eval)`. Each conforms to this contract and cites
this ADR.

**Rejected alternatives:**

- **Strands Agents SDK** — cleanest isolation and MCP-native, but durable multi-day pause/resume and
  hard loop control are builder-implemented; for staged regulated workflows that is the load-bearing
  capability LangGraph provides natively. Recorded as the **pre-vetted fallback** if LangGraph's
  dependency weight proves unmanageable.
- **CrewAI** — opinionated crew/role model is a looser fit for the committed supervisor→specialist
  routing tree and offers less loop control; neither safest-isolation nor most-controllable.
- **OpenAI Agents SDK** — vendor-locked to OpenAI; fails provider-agnostic + regulated/on-prem (C2).
- **No keystone (decide each tool independently)** — Rejected: the eval/framework collision that
  prompted this ADR; tools need one contract to conform to.

## Consequences

### Becomes Easier

- Durable, human-gated, multi-day workflows are native (checkpointer + `interrupt()`), not bespoke.
- Reasoning loop-safety has a built-in primitive (`recursion_limit`) for ADR-013 to build on.
- Dependent tool ADRs (009/010/013/017/037/045) have one explicit contract + order to follow.
- Governance traceability (human oversight, state history) maps to NIST/EU-AI-Act expectations.

### Becomes Harder

- LangGraph carries the heaviest dependency surface; the containment rule + CI-lint extension are
  now required maintenance, and reviewers must guard the orchestration-layer boundary.
- MCP is reached via an adapter bridge (slightly more glue than a native-MCP framework).
- The ecosystem pull toward LangSmith for eval must be actively resisted (ADR-045 stays OTLP-based).
- Checkpointing is not a full durable-execution engine; very long or exactly-once-critical flows may
  need an external durable runtime later.

## Applies To

- **MIRA-RUNTIME** — agent runtime built on the framework
- **MIRA-REASON** — reasoning loop expressed as graph nodes/edges
- **MIRA-ARCH** — provider/middleware seams the framework sits behind
- [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) / [ADR-002](./adr-002-provider-abstraction-pattern.md) / [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — isolation invariants referenced
- [ADR-009](./adr-009-middleware-pipeline-architecture.md) / [ADR-010](./adr-010-provider-agnostic-model-gateway.md) / [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) / [ADR-017](./adr-017-memory-architecture.md) / [ADR-037](./adr-037-bidirectional-guardrail-pipeline.md) / [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — dependent tool ADRs that conform to this contract
- [ADR-004](./adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md) — CI scaffold where the lint extension lands

## Links

- ADR file: `docs/adr/adr-007-core-agent-stack-and-framework.md`
- Research & rubric: `research/adr-007-core-agent-stack-and-framework.md`
- Framework comparison spike: `research/adr-007-agent-framework-and-stack.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-007
