# ADR-034: Per-Agent Identity & Task-Scoped Tokens

## Status

Accepted

## Context

Phase 1 ([ADR-033](./adr-033-phase-1-minimum-identity-slice.md), Accepted) ships a **single service
identity** shared by every domain specialist — sufficient to ship, but explicitly documented as a
limitation: "all specialists share one service identity until Phase 2 — cannot prove per-agent
least-privilege in Phase 1 audits." ADR-033 names this ADR by number as where that gap closes, and
defers in-flight token refresh here too ("task-scoped tokens make scoped re-issue tractable").

The domain-specialist supervisor topology ([ADR-014](./adr-014-domain-agent-supervisor-routing.md),
Accepted) already commits "each specialist is a per-agent identity / least-privilege boundary" and
cites this ADR as the decision that makes it real. Two specialists are built and shipped
(research, finance), both currently running under the Phase-1 shared identity.

This ADR does **not** re-decide authentication mechanics (JWT/JWKS validation is inherited from
the MCP-server ADR-005/007)
or entitlements enforcement (owned by the source data platform / MCP per
the inherited MCP-server ADR-022). It decides
how a per-agent, **task-scoped** credential is minted and relayed so each specialist exercises only
the entitlements its current task requires — narrower than domain-level, narrower than the Phase-1
single service identity.

## Decision Drivers

1. **ADR-033's explicit deferral** — "all specialists share one service identity until Phase 2 —
   cannot prove per-agent least-privilege in Phase 1 audits (documented limitation)"; this ADR
   closes that gap.
2. **ADR-014's committed identity boundary** — "each specialist is a per-agent identity /
   least-privilege boundary ([ADR-034])" is already written into an Accepted ADR; this is not a new
   requirement, it is fulfilling one already made.
3. **MIRA-IDENTITY epic acceptance criterion** — "each agent touches only what its task requires;
   agents are discoverable, verified end-to-end on customer data."
4. **Inherited entitlements boundary (MCP-server ADR-022)** — the source data platform is the
   entitlements authority; this
   ADR must narrow *which* MCP tools/entitlement groups a specialist's token can exercise, not
   re-implement ACL enforcement.
5. **Industry/standards alignment** — MCP's own authorization spec (co-developed with Anthropic)
   uses OAuth 2.0 Token Exchange (RFC 8693) for exactly this problem: exchanging a broader token for
   a narrower, audience-restricted one per sub-agent dispatch, rather than sharing one token across
   agents.
6. **Auditability, regulated setting** — the token-reuse-across-agents pattern is a named
   anti-pattern (privilege escalation, no per-agent audit trail, lateral-movement blast radius on
   compromise); this initiative's success criteria require observable, attributable calls.

## Research & Rubric

`Research & rubric — ADR-034`.
Scored RFC 8693 token exchange per specialist dispatch vs static per-specialist service accounts vs
a bespoke capability-token service against conformance to the inherited OIDC/MCP boundary,
least-privilege granularity, auditability, operational cost, and standards alignment. Token exchange
wins — it is the mechanism MCP's own authorization spec already uses, fits inside the existing
JWT/OIDC validation path without a second protocol, and is the only option delivering *task*-scoped
(not just domain-scoped) privilege with a verifiable delegation trail.

## Decision

Adopt **OAuth 2.0 Token Exchange (RFC 8693)** to mint a short-lived, task-scoped token per specialist
dispatch, relayed by the specialist in place of the shared Phase-1 service identity.

**1. Token exchange at dispatch time**
- When the supervisor ([ADR-014](./adr-014-domain-agent-supervisor-routing.md)) routes to a
  specialist subgraph, the runtime exchanges the caller's relayed token (per
  [ADR-033](./adr-033-phase-1-minimum-identity-slice.md)) via the
  `urn:ietf:params:oauth:grant-type:token-exchange` grant for a new token:
  - `resource`/`audience` restricted to the MCP tool surface the dispatch's task needs (e.g. the
    `ledger.*` tool prefix for a finance specialist task — see
    [ADR-020](./adr-020-source-connector-architecture.md) connector scoping).
  - `scope` narrowed to that task; a follow-on task for the same specialist requests a fresh
    exchange rather than reusing a broader token across tasks.
  - Short-lived (minutes, not the parent token's full lifetime) — this also resolves ADR-033's
    deferred mid-orchestration expiry problem: on expiry the specialist re-exchanges rather than
    failing the whole orchestration with a hard `401`.
- The **`act` claim** (RFC 8693) names the specialist as the current actor while preserving the
  original caller's `sub` — the delegation chain (user → supervisor → specialist) is verifiable
  end-to-end, matching ADR-033's attribution model (`tenant_id`/`user_id`/`correlation_id`).

**2. Specialist relay, not re-implementation**
- The specialist relays **only** the exchanged, task-scoped token to MCP — never the original
  broader token. This is a narrowing of ADR-033's existing "MCP token relay" component, not a new
  relay path.
- Entitlements enforcement remains entirely at the MCP/source-platform boundary
  (inherited MCP-server ADR-022) — the
  exchanged token narrows *which* entitlement-gated tools a specialist can even attempt to call; it
  does not replace the source data platform's ACL check.

**3. Failure mode**
- Token-exchange failure (IdP rejects the exchange, or the requested scope/audience is invalid for
  the caller) fails that specialist's dispatch closed — the supervisor treats it as a specialist
  failure per [ADR-014](./adr-014-domain-agent-supervisor-routing.md)'s failure-boundary policy
  (retry, reroute, or escalate to HITL per [ADR-039](adr-list.md)), never falling back to the
  broader Phase-1 shared identity.

**4. Scope of this ADR**
- Covers the **single-hop** supervisor→specialist case, matching ADR-014's current topology (no
  specialist-calls-specialist hops today). Multi-hop delegation chains, if introduced by dynamic
  composition ([ADR-015](adr-list.md)), are out of scope here — flagged as an open risk in the
  research doc for that future ADR to revisit.
- Does **not** cover agent discovery/cards (deferred to [ADR-035](adr-list.md), which this ADR's
  token-scoping model is designed to compose with) or prompt-injection defense
  ([ADR-036](adr-list.md), explicitly coupled to this ADR per the MIRA-IDENTITY epic).

**Rejected alternatives:**

- **Static per-specialist service accounts** — Rejected: only achieves domain-level scoping (a
  finance specialist's static account could act on any finance task, not just its current one); no
  per-task delegation trail.
- **Bespoke capability-token service** — Rejected: reinvents what RFC 8693 + MCP's authorization
  spec already standardize; introduces a new, unaudited security-critical component with no
  validation path through the existing `JWTValidator`; no interop with the emerging A2A agent-card
  auth model ADR-035 will need.

## Consequences

### Becomes Easier

- Each specialist provably touches only its current task's entitlements — closes the ADR-033
  Phase-1 audit gap and satisfies the MIRA-IDENTITY acceptance criterion.
- Mid-orchestration token expiry is no longer a hard failure: a short-lived, re-exchangeable token
  resolves the fail-fast limitation ADR-033 explicitly deferred here.
- The delegation chain (`act` claim + correlation ID) gives auditors a verifiable user→supervisor→
  specialist trail per dispatch, not just per request.
- Composes directly with ADR-035 (agent cards can declare the token-exchange auth scheme) and with
  MCP's own authorization spec — no bespoke protocol to maintain.

### Becomes Harder

- One additional network round trip (the token-exchange call) per specialist dispatch; bounded by
  ADR-014's existing supervisor↔specialist round-trip caps, but adds real latency that should be
  measured (candidate ADR-042 AgentOps span).
- Requires the chosen IdP to support the `token-exchange` grant type — not yet verified for this
  initiative's IdP profile (Cognito/Okta/Auth0/PingID/Azure AD per ADR-005/033); if unsupported, a
  lightweight in-process STS behind the same OIDC contract is the documented fallback.
- Multi-hop (specialist-calls-specialist) delegation is explicitly out of scope and only
  single-hop-tested; a future dynamic-composition ADR (ADR-015) must revisit scoping if that
  topology changes.

## Applies To

- **MIRA-IDENTITY** — this epic's primary Relevant ADR; ratification derives its
  first features per the epic's "Features are derived from the Relevant ADRs once ratified" note.
- **MIRA-AGENTS** — every domain specialist (research, finance) relays
  a task-scoped token instead of the Phase-1 shared identity.
- [ADR-014](./adr-014-domain-agent-supervisor-routing.md) — the supervisor→specialist dispatch this
  ADR scopes tokens for.
- [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — the Phase-1 slice this ADR closes the
  documented gap in; supersedes its "no in-flight token refresh" limitation for specialist dispatch.
- Phase 2 (coupled): [ADR-035](adr-list.md) (agent cards can declare this token-exchange scheme),
  [ADR-036](adr-list.md) (prompt-injection defense — explicitly coupled per the MIRA-IDENTITY epic).
- Inherited: MCP-server ADR-005 (authentication strategy, M2M and user tokens),
  MCP-server ADR-007 (JWT validation approach),
  MCP-server ADR-022 (entitlements enforcement model).

## Links

- ADR file: `docs/adr/adr-034-per-agent-identity-and-task-scoped-tokens.md`
- Research & rubric: `research/adr-034-per-agent-identity-and-task-scoped-tokens.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-034
- Epic: MIRA-IDENTITY
