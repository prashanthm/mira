# ADR-037: Bidirectional Guardrail Pipeline

## Status

Accepted

## Context

The product brief commits MIRA-SAFETY to "input/output guards, HITL escalation" so "unsafe I/O
blocked; risky actions need approval." Input and output are distinct attack surfaces (OWASP LLM01
Prompt Injection, LLM02 Insecure Output Handling), so guardrails must be **bidirectional**.
[ADR-009 (Proposed)](adr-list.md) defines *where* guardrails run (the guardrail-IN/-OUT stages of the middleware
chain); this ADR decides *what that pipeline is*. It must be framework-agnostic
([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment) and portable across every
deployment profile — including on-prem/Outposts where a cloud guardrail service is unavailable
([ADR-047](./adr-047-deployment-profiles-and-packaging.md)).

This ADR **composes** adjacent boundaries rather than re-deciding them: prompt-injection/tool-abuse
specifics are [ADR-036 (Proposed)](adr-list.md), hallucination/topic-drift are [ADR-038 (Proposed)](adr-list.md), HITL
escalation is [ADR-039 (Proposed)](adr-list.md).

## Decision Drivers

1. **Bidirectional threat surface** — input (LLM01) and output (LLM02) both need gating.
2. **Portability** — must run on every profile incl. on-prem, where no managed guardrail service exists.
3. **Defense-in-depth** — layered controls > a single control (NIST AI RMF / SP 800-53).
4. **ADR-009 / ADR-007** — guardrails are middleware stages, framework-agnostic.
5. **Composition** — works with ADR-036 (injection), ADR-038 (hallucination), ADR-039 (HITL).

## Research & Rubric

`Research & rubric — ADR-037`. Scored a custom bidirectional pipeline (primary) + optional cloud guardrail service (secondary) vs a cloud-service-only design vs output-only filtering against bidirectionality, prompt-injection coverage, portability across profiles, defense-in-depth, and ADR-009/007 fit. The custom-primary + optional-secondary design wins — portable to on-prem, layered, framework-agnostic. Self-contained on OWASP LLM Top 10, MITRE ATLAS, NIST AI RMF / SP 800-53; internal ADRs fix placement and adjacent boundaries.

## Decision

Adopt a **custom bidirectional guardrail pipeline** as the **primary** control, with an **optional
cloud guardrail service (e.g. Amazon Bedrock Guardrails) as a secondary defense-in-depth layer**
where the profile provides one.

**Pipeline (runs in the [ADR-009 (Proposed)](adr-list.md) guardrail-IN / guardrail-OUT stages):**

- **Input (guardrail-IN, before the agent graph):** prompt-injection / tool-abuse checks
  (detector design owned by [ADR-036 (Proposed)](adr-list.md)), topic-scope / domain checks, input PII handling.
  Block or escalate ([ADR-039 (Proposed)](adr-list.md)) on violation; fail closed.
- **Output (guardrail-OUT, before the response leaves — including error and `interrupt()` paths, and
  per-chunk for streaming [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)):**
  unsafe-content / data-leakage / format-conformance checks; hallucination & topic-drift signals
  ([ADR-038 (Proposed)](adr-list.md)); redaction.
- **Secondary layer (optional):** a managed cloud guardrail service runs **in addition to** the
  primary pipeline where available — never instead of it. No safety property may depend solely on the
  secondary layer (on-prem must be safe with the primary alone).
- **Framework-agnostic ([ADR-007](./adr-007-core-agent-stack-and-framework.md)):** the pipeline is
  middleware, not LangGraph internals; detectors call models through the gateway
  ([ADR-010 (Proposed)](adr-list.md)), not vendor SDKs.
- **Observable:** every block/allow/escalate emits a structured/OTel event ([ADR-009 (Proposed)](adr-list.md)
  telemetry stage) and feeds eval ([ADR-045 (Proposed)](adr-list.md)) and AgentOps ([ADR-042 (Proposed)](adr-list.md)).

**Rejected alternatives:**

- **Cloud guardrail service only** — Rejected: couples safety to one cloud, fails on-prem/Outposts
  ([ADR-047](./adr-047-deployment-profiles-and-packaging.md)), and is a single control layer (no
  defense-in-depth).
- **Output-only filtering** — Rejected: ignores input-side prompt injection (OWASP LLM01), the
  dominant agent threat.
- **Guardrails inside LangGraph nodes** — Rejected: violates ADR-007 containment and makes the
  safety boundary framework-specific (the ADR-009 chain is the boundary).

## Consequences

### Becomes Easier

- A single bidirectional boundary blocks unsafe input and output, portable to every profile.
- Defense-in-depth: optional cloud layer adds protection without creating a dependency.
- Composes cleanly with injection (036), hallucination (038), and HITL (039) decisions.
- Guardrail decisions are observable and feed eval/AgentOps.

### Becomes Harder

- Bidirectional checks add latency, worse over streaming (per-chunk output guarding).
- Detector tuning is ongoing; false positives block legitimate in-domain queries (needs override/HITL).
- Parity work: the primary pipeline must be complete on its own for on-prem, not lean on the secondary layer.
  The MIRA-SAFETY spec should define a **primary-pipeline completeness verification mechanism** — e.g.
  a `secondary_disabled` integration test that exercises every threat surface against the primary
  pipeline alone — to operationalize the "no safety property may depend solely on the secondary
  layer" hard rule.
- **Detector cost within ADR-013 bounds:** guardrail detector model calls (for LLM-based checks)
  count **inside** the per-run cost ceiling defined by ADR-013, not outside it. This means the
  ADR-013 ceiling must account for guardrail overhead; the relationship should be stated explicitly
  in the MIRA-REASON spec so that cost-ceiling tuning does not inadvertently disable guardrails.

## Applies To

- **MIRA-SAFETY** — guardrails (primary)
- **MIRA-IDENTITY** — input-side tool-abuse defense (with ADR-036)
- [ADR-009 (Proposed)](adr-list.md) — guardrail-IN/-OUT stages the pipeline runs in
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — containment (middleware, not framework internals)
- [ADR-036 (Proposed)](adr-list.md) (injection) / [ADR-038 (Proposed)](adr-list.md) (hallucination) / [ADR-039 (Proposed)](adr-list.md) (HITL) — composed boundaries
- [ADR-047](./adr-047-deployment-profiles-and-packaging.md) — portability incl. on-prem; [ADR-045 (Proposed)](adr-list.md)/[ADR-042 (Proposed)](adr-list.md) — eval/observability of guardrail decisions

## Links

- ADR file: `docs/adr/adr-037-bidirectional-guardrail-pipeline.md`
- Research & rubric: `research/adr-037-bidirectional-guardrail-pipeline.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-037
