
# ADR-032: Skills Registry, Versioning & Authorization

## Status

Accepted

## Context

The product brief names a **Skills registry** component ("Register, version, and authorize reusable
skills beyond one-off tools") and the MIRA-SKILLS epic commits to delivering "reusable, governed
skills beyond raw tools" for the source-agnostic agentic platform. A **skill** here is a higher-level,
composed capability — a named procedure that chains or conditions on one or more MCP tool calls,
distinct from a single one-off tool ([ADR-031](./adr-031-typed-tool-contracts.md), Accepted) — and
distinct from an `AgentSkill` entry in an [ADR-035](./adr-035-agent-cards-and-a2a-discovery.md) agent
card, which is routing/discovery **metadata** a specialist publishes about itself, not a versioned,
independently-authorizable artifact.

This initiative already has an **Accepted** versioned-registry pattern for prompts and tool
definitions ([ADR-012](./adr-012-prompt-tool-versioning.md) — content-addressed immutable versions,
dev→staging→prod promotion, eval-gated canary, runtime kill switch) and an **Accepted** typed-tool-
contract pattern that declares authorization on the contract while enforcing it at the inherited MCP
entitlements boundary ([ADR-031](./adr-031-typed-tool-contracts.md)). This ADR decides how a
**composed skill** is registered, versioned, and authorized as its own governed unit — reusing that
existing machinery rather than duplicating it, and without redefining or overlapping
[ADR-035](./adr-035-agent-cards-and-a2a-discovery.md)'s `AgentSkill` field.

## Decision Drivers

1. **MIRA-SKILLS epic charter** — "reusable, governed skills beyond raw tools" as a named, distinct
   platform component from the MCP tool surface.
2. **Reuse, don't rebuild** ([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment;
   ADR-012 precedent) — a second bespoke registry would duplicate ADR-012's storage, promotion, and
   kill-switch machinery for no new capability.
3. **Authorization correctness under composition** — a composed skill must not grant more privilege
   than the union of the tools it composes; declare-on-contract, enforce-at-MCP-boundary
   ([ADR-031](./adr-031-typed-tool-contracts.md)) is the pattern to extend, not re-implement
   (governance direction NIST's 2026 AI Agent Standards Initiative also converges on: least-
   privilege, task-scoped, enforced downstream of the declaration).
4. **Skill-registry supply-chain risk is real, not theoretical** — 2026 peer-reviewed research on
   `SKILL.md`-style registries shows unreviewed skill metadata can bias discovery/selection and evade
   governance checks; a governed, reviewed promotion pipeline (inherited from ADR-012) is the
   mitigation, not an optional nicety.
5. **Non-overlap with ADR-035** — `AgentSkill` in an agent card is routing metadata a specialist
   publishes about itself; this ADR's "skill" is a separately versioned, authorized, invocable
   artifact. The two must be named distinctly and cross-referenced, not merged.

## Research & Rubric

`Research & rubric — ADR-032`.
Scored (1) extending the ADR-012 registry with a new skill artifact kind composed of ADR-031 typed
tool contracts with declared, unioned authorization vs (2) a bespoke separate skills registry and
versioning scheme vs (3) no registry — skills as code, versioned only by deploy — against fit to the
epic charter, reuse vs. duplication, authorization correctness under composition, rollback/kill-switch
capability, versioning-scheme clarity, and operational cost. Extending the ADR-012 registry wins — it
inherits rollback, promotion, and audit for free, and reuses ADR-031's declare-then-enforce
authorization split rather than inventing a parallel one. Grounded in the current (2026) Agent Skills
open standard for the "skill" vocabulary, SemVer-for-skills practice, peer-reviewed skill-registry
security research, and this initiative's own Accepted ADR-012/031/035.

## Decision

Register a **skill as a new versioned artifact kind in the ADR-012 registry**: a named, composed
capability built from one or more [ADR-031](./adr-031-typed-tool-contracts.md) typed tool contracts
(plus optional prompt/procedure text), authorized by the **union of its component tools'** declared
entitlement requirements, enforced at the same inherited MCP entitlements boundary those tools already
use.

**1. What a skill is (and is not)**
- A skill is an **ordered or conditional composition of one or more tool contracts** — e.g. "query
  the ledger → resolve categories → summarize spend" — registered under a stable name, distinct from
  any single [ADR-031](./adr-031-typed-tool-contracts.md) tool.
- A skill is **not** an `AgentSkill` entry in an [ADR-035](./adr-035-agent-cards-and-a2a-discovery.md)
  agent card. An agent card's `skills` array is routing/discovery metadata a specialist publishes
  about what it can do; a registry skill (this ADR) is the versioned, invocable artifact that
  publication may point at. A specialist's `AgentSkill` entry MAY reference a registry skill's name,
  but the two are not the same object and this ADR does not restate ADR-035's schema.

**2. Registration & versioning (extends ADR-012)**
- Skills are **content-addressed, immutable versions with a moving `active` pointer per environment**
  — the identical model ADR-012 already uses for prompts/tools — stored behind the same Protocol seam
  ([ADR-002](./adr-002-provider-abstraction-pattern.md)).
- A skill version declares a **compatibility range** against the versions of the tool contracts it
  composes (mirroring ADR-012 §1's tool-definition compatibility-range field), so a skill does not
  silently break when a composed tool is promoted to an incompatible new version.
- **Version scheme:** semantic versioning (MAJOR.MINOR.PATCH). MAJOR = a composed step is removed/
  reordered in a way that changes required inputs or output shape; MINOR = an additional optional
  step or output field; PATCH = internal prompt/procedure tuning with no interface change.

**3. Staged promotion & rollback (inherits ADR-012 wholesale)**
- A skill version is promoted **dev → staging → prod** and must **pass the
  [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) eval suite** in staging before reaching `prod`,
  identically to a prompt/tool version.
- New prod skill versions release via the same **eval-gated canary** ADR-012 defines; the same
  **runtime kill switch** reverts a skill's `active` pointer to last-known-good with no code deploy.
- Every registration, promotion, canary decision, and rollback emits the same structured/OTel audit
  event ADR-012 §5 already defines — no separate audit path.

**4. Authorization (extends ADR-031's declare-then-enforce split)**
- A skill's **declared entitlement requirement is the union of its composed tools' declared
  entitlements** ([ADR-031](./adr-031-typed-tool-contracts.md) §3) — a skill cannot declare, and
  therefore cannot grant, more privilege than its parts already require. Composition never escalates
  privilege.
- **Enforcement stays at the inherited MCP entitlements boundary** (inherited MCP-server entitlements
  model) via the invoking agent's task-scoped identity
  ([ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md)): a skill only executes to
  completion if the caller's token already covers every entitlement its composed tool calls require.
  This ADR does not add a second authorization check outside that boundary.
- A skill registration that composes tools whose combined entitlement union exceeds what any
  realistic task-scoped identity would hold is a **registration-time review flag**, not a runtime
  bypass — reviewed at promotion (ADR-012's staged pipeline), not auto-approved.

**Rejected alternatives:**

- **Bespoke separate skills registry, own versioning scheme** — Rejected: duplicates ADR-012's
  storage/promotion/kill-switch machinery for no corresponding new capability; two systems to keep
  behaviorally consistent is an unjustified operational-surface and drift risk.
- **No registry — skills as code, versioned by deploy** — Rejected: forfeits ADR-012's rollback/audit
  guarantees (the exact incident-prone failure mode ADR-012 was written to close) and leaves
  composed-capability authorization undeclared and unreviewed — the operational-text/supply-chain risk
  current skill-registry security research documents.

## Consequences

### Becomes Easier

- A bad composed skill is caught on a canary slice and revertible instantly via the inherited
  ADR-012 kill switch — no separate rollback mechanism to build.
- Authorization for a composed capability is provably no broader than its parts — a skill cannot be
  used to smuggle in privilege a reviewer wouldn't grant to any single component tool.
- One registry, one audit trail, one promotion pipeline for prompts, tools, *and* skills — no drift
  between two governance systems.
- Adding a new skill is a registration against existing tool contracts, not new infrastructure.

### Becomes Harder

- The ADR-012 registry's artifact-kind schema and promotion pipeline must be extended to validate
  skill-specific concerns (composed-tool compatibility ranges, entitlement-union computation) — real,
  if incremental, engineering work on an already-shipped system.
- Skill-to-tool compatibility-range checking adds a new failure mode at promotion time (a skill can
  be blocked by an incompatible tool version bump it doesn't control) that must be surfaced clearly
  to skill authors, not silently fail.
- The skill/`AgentSkill` naming collision with ADR-035 is a recurring documentation and onboarding
  hazard; every reference to "skill" in this initiative must disambiguate which of the two it means.

## Applies To

- **MIRA-SKILLS** — primary; fulfills the epic's "governed first-class units
  distinct from one-off tools" commitment.
- **MIRA-TOOLS** — every skill composes ADR-031 typed tool contracts; this ADR does
  not redefine tool contracts.
- **MIRA-EVAL** — skill promotion reuses the ADR-012/ADR-045 eval-gated canary.
- **MIRA-IDENTITY** — skill authorization is enforced via ADR-034 task-scoped
  identity at the inherited MCP entitlements boundary.
- [ADR-012](./adr-012-prompt-tool-versioning.md) — the versioned-registry pattern this ADR extends
  with a new skill artifact kind.
- [ADR-031](./adr-031-typed-tool-contracts.md) — the typed tool contracts a skill composes; the
  declare-then-enforce authorization split this ADR reuses.
- [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md) — the task-scoped identity that
  enforces a skill's unioned entitlement requirement at invocation.
- [ADR-035](./adr-035-agent-cards-and-a2a-discovery.md) — `AgentSkill` is agent-card routing metadata,
  a distinct concept this ADR does not overlap or redefine; a card's `AgentSkill` entry may reference
  a registry skill's name.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — the eval gate a skill version must pass
  before promotion, identically to prompts/tools.

## Links

- ADR file: `docs/adr/adr-032-skills-registry-versioning-and-authorization.md`
- Research & rubric: `research/adr-032-skills-registry-versioning-and-authorization.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-032
- Epic: MIRA-SKILLS
