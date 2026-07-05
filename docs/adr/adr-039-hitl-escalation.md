# ADR-039: Human-in-the-Loop Escalation

## Status

Accepted

## Context

Some agent actions are too consequential to execute autonomously: tool calls annotated
`destructiveHint` in their [ADR-031](./adr-031-typed-tool-contracts.md) contracts, actions flagged
by [ADR-036](./adr-036-prompt-injection-and-tool-abuse-defense.md) injection findings, and runs
approaching their [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) cost/step ceilings.
The reasoning loop already has the pause primitive — ADR-013 adopted `interrupt()` HITL gates
(`orchestration/interrupts.py`, `ReasoningLoop.resume`), and durable execution means a paused run
survives until a human responds without holding compute.

What was open is **policy** (which actions escalate, and to what) and **mechanism** (how an
escalation reaches a human). The policy candidates were annotation-driven, risk-score-driven, or
per-tenant configurable; the mechanism candidates were an async webhook callback, a synchronous
approval UI, and a polling inbox.

## Decision Drivers

1. **Structural, deterministic classification** — risk must be computable offline from facts the
   platform already holds (contract annotations, guardrail findings, budget state), not from a
   model's self-assessment.
2. **Fail-closed composition** — the same signals that fail closed in guardrail-IN (unknown tool,
   out-of-contract args) must classify as high risk here, so the two layers agree.
3. **Reuse the ADR-013 pause** — escalation must convert into the existing `require_hitl` /
   `interrupt()` gate, not a second pause mechanism.
4. **Transport independence** — core must not bind to a delivery channel; Phase-E incident routing
   (ADR-044) reuses the same notification seam.
5. **Auditability** — every escalation decision is itself audit-relevant (ADR-040) and carries the
   correlation ID (ADR-033).

## Decision

Adopt a **three-tier structural risk policy with tier-mapped escalation actions and an injectable
webhook notification seam**, implemented in `src/mira/core/escalation.py`:

- **`RiskPolicy`** — classifies a proposed action (`ActionContext`: tool name, args, injection
  findings, budget fraction) into `RiskTier = low | medium | high` with recorded reasons:
  - **high**: the tool's contract carries `destructiveHint`; a matched injection finding
    accompanies the action; the tool is unknown to the contract registry; or the arguments fail
    the contract's `inputSchema` — the same fail-closed signals ADR-036 blocks on.
  - **medium**: cost/step budget consumption at or above a configurable threshold fraction
    (default 0.8) of the ADR-013 ceiling.
  - **low**: everything else.
- **`EscalationPolicy`** — maps tier to decision: **high → `hold_for_approval`**
  (`EscalationDecision.require_hitl` is true — the reasoning loop routes through its `interrupt()`
  gate, or the pipeline rejects), **medium → `notify`** (proceed, but a human is informed),
  **low → `proceed`**. Approval resumes the durable run via `ReasoningLoop.resume`, with the
  decision recorded in the ADR-040 trace.
- **`WebhookNotifier`** — the mechanism seam: an async-free callback taking an injectable
  `transport: Callable[[dict], None]` (default: an in-memory `sent` list for tests/offline
  profiles). `notify(decision, context)` posts a structured payload
  `{tier, action, reasons, correlation_id[, timestamp]}` — the timestamp appears only when an
  injectable clock is supplied (no wall-clock default). Production wires the transport to
  ticketing/chat per the ADR-006 webhook conventions; Phase-E incident routing (ADR-044) reuses
  this exact seam.

**Rejected alternatives:**

- **Model-scored risk** — Rejected: unverifiable and gameable by the very content being guarded
  against; structural signals are deterministic and testable in CI.
- **Synchronous approval UI as the primary mechanism** — Rejected as primary: couples escalation
  latency to an interactive session; long-running background workflows need the async callback.
  A UI remains a consumer of the same webhook seam, not a separate mechanism.
- **Annotation-only policy (destructive = escalate, nothing else)** — Rejected: misses injection
  findings and budget pressure, both of which the platform already computes.

## Consequences

### Becomes Easier

- One deterministic policy answers "does this action need a human?" from facts already in hand;
  tests assert every tier transition offline.
- The reasoning loop needs no new pause machinery — `hold_for_approval` maps directly onto the
  existing `require_hitl` / `interrupt()` gate.
- Phase-E incident routing gets its notification seam for free.

### Becomes Harder

- Threshold governance: the budget fraction and tier mapping are policy knobs that need per-tenant
  review as usage grows.
- The caller must assemble `ActionContext` honestly (budget fraction, findings); the policy cannot
  see what it is not shown.

### Deferred

- **Async webhook transport** (real HTTP delivery, retries, signing) behind the injected
  `transport` callable — core stays network-free.
- **Approval timeout policy** (deny-by-default on expiry vs. queue) and approver
  identity/authorization — recorded as an open policy question for the tenant-configuration layer;
  approvals must not widen the ADR-034 task-scoped token.
- Per-tenant configurable tier mappings.

## Applies To

- **MIRA-SAFETY** — risky actions need approval (with ADR-037/038).
- [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) — the `interrupt()` gate and budgets this policy drives.
- [ADR-031](./adr-031-typed-tool-contracts.md) — `destructiveHint` and `inputSchema` as risk signals.
- [ADR-036](./adr-036-prompt-injection-and-tool-abuse-defense.md) — injection findings as high-risk input.
- [ADR-040](./adr-040-decision-trace-audit.md) — escalation decisions land in the decision trace.
- [ADR-044](./adr-044-incident-detection-and-remediation.md) — Phase-E reuse of the webhook seam.

## Links

- ADR file: `docs/adr/adr-039-hitl-escalation.md`
- Implementation: `src/mira/core/escalation.py`; tests: `tests/test_escalation.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-039
