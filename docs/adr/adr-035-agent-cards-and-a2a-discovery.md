# ADR-035: Agent Cards & A2A Discovery

## Status

Accepted

## Context

The domain-specialist supervisor topology ([ADR-014](./adr-014-domain-agent-supervisor-routing.md),
Accepted) already commits three times over that "specialists are discoverable via agent cards" and
names this ADR as the decision that makes it real — explicitly rejecting static if/else routing as
"brittle as domains/skills grow" in favor of "agent-card-driven routing [that] scales with the
discoverable set." The MIRA-IDENTITY epic's own "What We're Building" line already names "published
A2A-style agent cards" as the direction; this ADR formalizes an already-committed choice rather than
introducing a new one.

This ADR composes directly with [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md)
(Proposed, drafted the same session), which states it "composes directly with ADR-035 (agent cards
can declare the token-exchange auth scheme)" — the two ADRs must agree on how a specialist declares
its auth scheme, not invent two separate mechanisms.

This ADR does **not** re-decide tool access (MCP, inherited and already governing
[ADR-020](./adr-020-source-connector-architecture.md) connector scoping) or token minting/scoping
(ADR-034). It decides how specialists **publish** discoverable capability metadata and how the
supervisor **discovers** them.

## Decision Drivers

1. **ADR-014's committed discovery mechanism** — "specialists are discoverable via agent cards
   (ADR-035)" is already written into an Accepted ADR, cited three times; this is fulfilling a
   requirement already made, not creating one.
2. **ADR-014's explicit rejection of static routing** — "Static if/else routing (no agentic
   supervisor) — Rejected: brittle as domains/skills grow." A discovery mechanism that doesn't scale
   with the specialist set repeats this rejected pattern.
3. **MIRA-IDENTITY epic commitment** — "published A2A-style agent cards" is already the named
   direction in the epic's problem/build statement.
4. **Composability with ADR-034** — task-scoped tokens (ADR-034) need a place to declare their auth
   scheme per specialist; the discovery mechanism and the identity mechanism must agree on one
   declaration surface, not two.
5. **Standards maturity and layering** — A2A (Agent2Agent protocol) reached v1.0 in 2026 under
   Linux Foundation governance, and its own documentation explicitly frames it as complementary to
   MCP: "A2A is about agents partnering on tasks, while MCP is more about agents using capabilities"
   — matching this initiative's supervisor↔specialist (A2A) vs specialist↔tool (already-inherited
   MCP) split exactly.

## Research & Rubric

`Research & rubric — ADR-035`. Scored an
A2A-standard `AgentCard` (served via well-known URI, discovered via direct/private configuration)
against a bespoke internal service registry and a hard-coded routing table, on conformance to the
already-committed direction, composability with ADR-034, scaling with the discoverable set, standards
alignment, and operational cost. The A2A `AgentCard` wins — it is the direction the epic and ADR-014
already name, its `securitySchemes`/`security` fields are exactly where ADR-034's token-exchange
scheme is declared with no adapter layer needed, and it is the only option that scales the way
ADR-014 requires without repeating the rejected static-routing anti-pattern.

## Decision

Adopt the **A2A `AgentCard` schema** for specialist (and supervisor) discovery metadata, published at
a well-known URI, discovered by the supervisor via **direct/private configuration** of the deployed
specialist set (not a dynamic runtime registry — see Scope below).

**1. Card publication**
- Each specialist subgraph ([ADR-014](./adr-014-domain-agent-supervisor-routing.md)) publishes an
  `AgentCard` JSON document at `/.well-known/agent-card.json` on its service endpoint, declaring:
  - `id`, `name`, `description`, `version` — identity metadata.
  - `skills` — one `AgentSkill` entry per domain capability (e.g. a finance specialist declares a
    `finance-query` skill), each with `tags` for routing and `inputModes`/`outputModes`.
  - `securitySchemes` / `security` — the ADR-034 OAuth2 token-exchange scheme
    (`urn:ietf:params:oauth:grant-type:token-exchange`), declared as an `OAuth2SecurityScheme` — the
    **same** field A2A already defines for this, not a bespoke extension.
  - `capabilities` — streaming/push-notification flags as applicable to the specialist's response
    shape.
- The supervisor publishes its own `AgentCard` for symmetry and future composability (e.g. if a
  higher-level orchestrator or an external system needs to discover the supervisor itself), though
  its primary role in Phase 2 is consumer, not published target.

**2. Discovery**
- The supervisor discovers specialists via **direct/private configuration** — a fixed,
  operator-deployed list of specialist endpoints (research, finance today), each
  resolved to its `AgentCard` at startup or on a refresh interval. This is the third of A2A's three
  documented discovery strategies (well-known URI + curated registry + direct/private config), chosen
  because the specialist set is operator-deployed and fixed, not an open marketplace.
- The supervisor does **not** implement or depend on A2A's curated-registry discovery strategy — the
  spec does not yet standardize a registry API (see Open Risks in the research doc); adopting it
  now would build against an unfinished part of the standard.
- Routing decisions ([ADR-014](./adr-014-domain-agent-supervisor-routing.md)) use each discovered
  card's `skills`/`tags` to select the specialist for a given query, replacing what would otherwise
  be a hard-coded routing table.

**3. Card authenticity**
- Cards carry an `AgentCardSignature` per the A2A spec. Signature verification is an implementation
  concern for the build phase, not re-specified here — flagged as an open risk in the research doc.

**4. Scope of this ADR**
- Covers **card publication and supervisor-side discovery** for the fixed, operator-deployed
  specialist set. Does not cover dynamic workflow composition ([ADR-015](adr-list.md), Phase 3,
  which will consume this discoverable set for more than static routing) or agent scaffolding
  ([ADR-016](adr-list.md), Phase 3, which wires a card at specialist-creation time).
- Does not redefine token scoping — the `security`/`securitySchemes` declaration references
  [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md)'s mechanism, it does not restate it.

**Rejected alternatives:**

- **Bespoke internal service registry** — Rejected: contradicts the epic's own committed direction
  ("A2A-style agent cards") and reinvents a schema A2A already standardizes, with no interop path.
- **Hard-coded routing table** — Rejected: ADR-014 already rejected static if/else routing for the
  identical reason (brittle as domains/skills grow); a hard-coded discovery table is that same
  anti-pattern applied to discovery instead of routing logic.

## Implemented Mechanism (Phase F)

Building on the Phase-B slice (`src/mira/orchestration/agent_cards.py`: in-process `AgentCard` +
`AgentCardRegistry` with the deterministic keyword matcher the supervisor routes against), Phase F
adds the **well-known discovery surface** on the warm service (`src/mira/core/service.py`; tests:
`tests/test_agent_discovery.py`); the decision text above is unchanged.

- **`GET /.well-known/agent-cards`** (`AGENT_CARDS_PATH`) serves the deployed card set as
  `{"cards": [...]}` — each entry the A2A-shaped `AgentCard.to_dict()` payload (name, description,
  version, capabilities with tool prefixes + routing keywords).
- The card set is supplied by an optional **`agent_cards` provider callable** on
  `WarmService`/`create_app` (typically `lambda: [c.to_dict() for c in registry.cards()]`),
  evaluated per request so the served set tracks the live registry. Unconfigured discovery is
  **fail-closed**: `503 {"error": "discovery_unavailable"}`, matching the `/explain` unconfigured
  behaviour.
- Consumers: ADR-014 routing and ADR-015 composition read the same registry the endpoint serves,
  so what a remote peer discovers is exactly what the supervisor composes from; ADR-016 scaffolded
  agents ship their card snippet at creation.

Deferred (unchanged from the decision's scope): **remote A2A card fetch** (supervisor-side
resolution of *other* services' well-known URIs — today's specialist set is in-process, so
publication landed first), per-specialist card endpoints (one service publishes the set), and
`AgentCardSignature` signing/verification, still an open implementation-phase risk.

## Consequences

### Becomes Easier

- Adding a new specialist (or a future domain beyond research/finance) means publishing a
  new `AgentCard` and adding it to the supervisor's configured set — no routing-logic code change.
- Auth scheme declaration and token scoping (ADR-034) share one field (`securitySchemes`/`security`)
  instead of a bespoke parallel mechanism.
- The supervisor's routing decisions are traceable to a specific, versioned card rather than
  implicit knowledge baked into code — improves the auditability this initiative's regulated setting
  requires.
- Standards alignment gives a real interop path if a future initiative or third-party agent needs to
  discover Mira specialists, or vice versa.

### Becomes Harder

- A2A is a young standard (v1.0 in 2026); its ecosystem and tooling will keep evolving, and this ADR
  may need revisiting if the spec makes breaking changes before Phase 2 implementation lands.
- The curated-registry discovery strategy is explicitly out of scope because A2A hasn't standardized
  a registry API yet — if the specialist set later needs dynamic, runtime-queryable discovery (not a
  fixed deployed set), that requires either a spec update or a bespoke registry layered on top, not
  covered by this decision.
- Card-signing/verification tooling maturity was not verified in this research — an implementation-
  phase risk, not an architectural one.

## Applies To

- **MIRA-IDENTITY** — fulfills the epic's "published A2A-style agent cards"
  commitment; ratification derives its first features alongside ADR-034 per the epic's "Features are
  derived from the Relevant ADRs once ratified" note.
- **MIRA-AGENTS** — every domain specialist (research, finance)
  publishes an `AgentCard`; the supervisor's routing consumes them.
- [ADR-014](./adr-014-domain-agent-supervisor-routing.md) — the supervisor routing model this ADR
  supplies discovery metadata for; fulfills its "discoverable via agent cards" commitment.
- [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md) — shares the
  `securitySchemes`/`security` declaration surface; this ADR does not redefine token scoping.
- Phase 3 (consumes this ADR's discoverable set): [ADR-015](adr-list.md) (dynamic workflow
  composition), [ADR-016](adr-list.md) (agent scaffolding wires a card at creation).
- Inherited: MCP tool layer ([ADR-007](./adr-007-core-agent-stack-and-framework.md),
  [ADR-020](./adr-020-source-connector-architecture.md)) — A2A discovery is a distinct, complementary
  layer above specialist-to-MCP-tool calls, not a replacement for them.

## Links

- ADR file: `docs/adr/adr-035-agent-cards-and-a2a-discovery.md`
- Research & rubric: `research/adr-035-agent-cards-and-a2a-discovery.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-035
- Epic: MIRA-IDENTITY
