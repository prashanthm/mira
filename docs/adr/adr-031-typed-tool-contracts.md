# ADR-031: Typed Tool Contracts

## Status

Accepted

## Context

The product brief commits MIRA-TOOLS to "predictable tool behavior and errors for agents — typed
contracts, retry policy, authorization." Agents consume tools over the inherited **FastMCP/MCP tool
surface** (inherited MCP-server ADR-001/ADR-002) — which this ADR must conform to,
not fork. This ADR decides the **contract shape**: how a tool declares its types, idempotency/retry
semantics, and authorization needs. The contract is **versioned by [ADR-012](./adr-012-prompt-tool-versioning.md)**
and **enforced/validated in the [ADR-009](./adr-009-middleware-pipeline-architecture.md) middleware**;
authorization is *declared* here but *enforced* at the inherited MCP entitlements boundary
(inherited MCP-server ADR-022 — entitlements enforcement model).

## Decision Drivers

1. **MIRA-TOOLS** — predictable tool behavior/errors: typed contracts, retry policy, authorization.
2. **Inherited FastMCP surface** — conform to the MCP tool definition; do not invent a parallel protocol.
3. **Safe retries / predictability** — idempotency must be declared so retries/dedup are safe.
4. **Bounded agency (OWASP LLM06)** — destructive/open-world hints + declared authz bound agent action.
5. **Versionable + enforceable** — the contract is versioned by ADR-012 and validated in ADR-009.

## Research & Rubric

`Research & rubric — ADR-031`. Scored MCP-native typed contracts (JSON Schema + tool annotations + idempotency/retry + authz metadata) vs ad-hoc conventions vs a bespoke parallel format against machine-checkable types, declared idempotency/authz, risk hints, conformance to the inherited FastMCP surface, LLM-friendliness, and versionability. The MCP-native option wins — schema-first, conforms to the inherited surface, and carries exactly the catalog's required metadata. Self-contained on the MCP specification + tool-design practice + NIST/OWASP; internal ADRs fix where it plugs in.

## Decision

Define every agent-consumed tool as a **typed MCP contract**: the inherited MCP tool definition
extended with idempotency, retry, and authorization metadata.

**1. Schema (typed, flat)**
- Name + description (the description is LLM context) + **JSON Schema `inputSchema`** with strict
  types ([MCP spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)).
- **Keep schemas flat** — prefer splitting a tool over deep nesting (token/latency/parse cost). Declare
  an **output schema** where it aids the agent.

**2. Behavior metadata (MCP tool annotations)**
- `readOnlyHint`, `idempotentHint`, `destructiveHint`, `openWorldHint` declared per tool.
- **Idempotency:** idempotent tools carry/accept an **idempotency key** so retries and dedup are safe;
  non-idempotent behavior is documented explicitly. **Retry policy** (retryable error classes, backoff)
  and a **per-tool timeout** are part of the contract; failures surface as structured tool errors.

**3. Authorization metadata**
- Each tool **declares the entitlement it requires**. The declaration is on the contract; **enforcement
  stays at the inherited MCP entitlements boundary** (inherited MCP-server ADR-022 — entitlements enforcement model)
  with Phase-2 per-agent task-scope narrowing ([ADR-034](./adr-list.md)) — not re-implemented here.

**4. Integration**
- Tool definitions are **versioned by [ADR-012](./adr-012-prompt-tool-versioning.md)** (registry, staged
  rollout, kill switch) and **validated in the [ADR-009](./adr-009-middleware-pipeline-architecture.md)
  middleware**; the contract is **framework-agnostic** ([ADR-007](./adr-007-core-agent-stack-and-framework.md)).
- Annotations are **hints, not guarantees** — the runtime still treats tool output defensively
  (guardrails, [ADR-037](./adr-list.md)).

**Rejected alternatives:**

- **Ad-hoc per-tool conventions (free-form, no enforced schema/metadata)** — Rejected: no
  machine-checkable types, no declared idempotency/authz; unpredictable behavior (OWASP LLM06).
- **Bespoke contract format parallel to MCP** — Rejected: re-decides and forks the inherited FastMCP
  surface (inherited MCP-server ADR-001 forbids a parallel tool protocol).
- **Deeply nested rich schemas** — Rejected: higher token cost, latency, and parse errors; split
  into simpler tools instead.

## Consequences

### Becomes Easier

- Agents get predictable, machine-validated tool behavior and errors.
- Safe retries/dedup via declared idempotency; destructive/open-world hints bound risky calls.
- Conforms to the inherited MCP surface — no protocol fork; versionable + enforceable.
- Authorization is declared once on the contract, enforced at the existing MCP boundary.

### Becomes Harder

- Every tool author must specify schema + annotations + idempotency/retry/authz — more upfront rigor.
- Keeping schemas flat conflicts with rich domain types (e.g. nested document-section or
  ledger-entry shapes) — pushes toward more, simpler tools.
- The declaration/enforcement split (here vs MCP boundary) must be kept clear to avoid double-implementation.

## Applies To

- **MIRA-TOOLS** — typed tool contracts (primary)
- [ADR-012](./adr-012-prompt-tool-versioning.md) — versions/rolls out tool definitions
- [ADR-009](./adr-009-middleware-pipeline-architecture.md) — validates contracts at the boundary
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — framework-agnostic contract
- [ADR-034](./adr-list.md) (task-scoped authz) / [ADR-037](./adr-list.md) (defensive output handling) / [ADR-032](./adr-list.md) (skills build on tools)
- Inherited: MCP-server ADR-001 (FastMCP), MCP-server ADR-022 (entitlements enforcement)

## Links

- ADR file: `docs/adr/adr-031-typed-tool-contracts.md`
- Research & rubric: `research/adr-031-typed-tool-contracts.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-031
- Epic: MIRA-TOOLS
