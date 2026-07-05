# ADR-012: Prompt & Tool Versioning with Staged Rollout & Kill Switch

## Status

Accepted

## Context

The product brief commits MIRA-EVAL to "version-controlled prompts/tools, staged rollout, kill
switches" so that "bad prompts/tools roll back." Prompt changes are a leading cause of LLM production
incidents, and the ability to revert is a managed-risk obligation (NIST AI RMF / EU AI Act). This ADR
decides how prompts and tool definitions are versioned, promoted to production, and reverted.

It fits the locked architecture: the model gateway ([ADR-010](./adr-010-provider-agnostic-model-gateway.md))
resolves the *active* version but defers the versioning/rollout/kill-switch **design** to this ADR;
the eval suite ([ADR-045](./adr-045-eval-framework-ci-safety-gate.md)) provides the quality gate a
canary is judged against; the design must be **framework-agnostic** ([ADR-007](./adr-007-core-agent-stack-and-framework.md)
containment) and align with the [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)
versioning conventions.

## Decision Drivers

1. **MIRA-EVAL** — version-controlled prompts/tools, staged rollout, kill switches; "bad prompts/tools roll back."
2. **Prompt changes drive incidents** — gated rollout + instant revert is risk control, not gold-plating.
3. **Governance (NIST AI RMF / EU AI Act)** — change management and reversibility for high-risk AI.
4. **Reuse, don't rebuild** — the canary quality check is the ADR-045 eval suite; the active version
   is resolved at the ADR-010 gateway.
5. **ADR-007 containment** — versioning/rollout is framework-agnostic, not LangGraph-internal.

## Research & Rubric

`Research & rubric — ADR-012`. Scored a versioned registry + eval-gated canary + kill switch vs git-only-deploy-to-change vs hot-edit-no-versioning against version history, catching bad changes before broad exposure, instant code-deploy-free rollback, staged promotion, governance, and ADR-007/010 fit. The registry + canary + kill-switch design wins — it is the established LLMOps progressive-delivery pattern and serves the "roll back" outcome directly. Self-contained on LLMOps/progressive-delivery practice, feature-flag/kill-switch patterns, and NIST/EU-AI-Act; internal ADRs fix where it plugs in.

## Decision

Adopt a **versioned registry for prompts and tool definitions, with eval-gated canary rollout and a
runtime kill switch.**

**1. Versioning**
- Prompts and tool definitions are **first-class versioned artifacts** (content-addressed; immutable
  versions; a moving `active` pointer per environment). Stored behind a Protocol seam
  ([ADR-002](./adr-002-provider-abstraction-pattern.md) `IStateStore`/object store; concrete store is
  the storage-engine ADR's call), **not** in framework-native prompt stores (ADR-007 containment).
- Tool-definition versions carry their typed-contract metadata ([ADR-031](./adr-list.md)) and a
  declared compatibility range against the MCP tool surface.

**2. Staged promotion**
- A version is promoted **dev → staging → prod**. A version cannot reach `prod` until it **passes
  the [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) eval suite** in staging.

**3. Canary rollout (eval-gated)**
- A new prod version is released to a **small traffic slice (start 5–10%)**; the **ADR-045 eval**
  runs on canary traffic (quality, not just infra health), alongside latency/cost signals
  ([ADR-042](./adr-list.md)). The version auto-promotes on passing thresholds or halts on failure.
- The gateway ([ADR-010](./adr-010-provider-agnostic-model-gateway.md)) resolves which version a given
  request uses (cohort/percentage), so callers and business logic never pick versions directly.

**4. Kill switch (instant revert)**
- A **runtime kill switch** reverts the `active` pointer to the **last-known-good** version with **no
  code deploy** — the emergency-reversal pattern. Scope (per-prompt/per-tool vs global) and who may
  trigger it (ops / HITL, [ADR-039](./adr-list.md)) are policy in the feature spec.

**5. Audit**
- Every promotion, canary decision, and rollback emits a structured/OTel event and a decision-trace
  record ([ADR-040](./adr-list.md)/[ADR-042](./adr-list.md)) so change history is queryable.

**Rejected alternatives:**

- **Git-only versioning, deploy-to-change** — Rejected: no runtime rollback (a bad prompt needs a
  redeploy), no canary; MTTR is a deploy cycle — unacceptable given prompt changes drive most incidents.
- **Hot-editable prompts, no versioning** — Rejected: no history, no staged rollout, no safe revert;
  the exact incident-prone failure mode.
- **Framework-native prompt store (e.g. LangSmith prompt hub)** — Rejected: re-introduces the
  ecosystem coupling the ADR-007 containment rule forbids; versioning stays behind the Protocol seam.

## Consequences

### Becomes Easier

- A bad prompt/tool change is caught on a canary slice (eval-gated) before broad exposure.
- Instant, code-deploy-free rollback to a known-good version — the "roll back" outcome.
- Full version history + audit trail for change management (governance).
- Reuses the eval gate (ADR-045) and gateway version-resolution (ADR-010); nothing rebuilt.

### Becomes Harder

- A registry + flagging/canary system is operational surface to build and run.
- Canary thresholds and traffic % need tuning; too tight blocks good changes, too loose lets a bad
  one reach more users.
- Prompt↔tool version-skew compatibility must be checked at promotion.

## Applies To

- **MIRA-EVAL** — versioning, staged rollout, kill switches (primary)
- **MIRA-MODEL** — gateway resolves the active version
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — eval suite gates the canary
- [ADR-010](./adr-010-provider-agnostic-model-gateway.md) — version resolution at the gateway
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — framework-agnostic, behind the Protocols
- [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) — versioning conventions
- [ADR-031](./adr-list.md) (typed tool contracts) / [ADR-040](./adr-list.md) (decision traces) / [ADR-042](./adr-list.md) (telemetry) / [ADR-039](./adr-list.md) (kill-switch authority)

## Links

- ADR file: `docs/adr/adr-012-prompt-tool-versioning.md`
- Research & rubric: `research/adr-012-prompt-tool-versioning.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-012
- Epic: MIRA-EVAL
