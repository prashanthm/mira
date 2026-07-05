# ADR-016: Agent Scaffolding & Generation

Status: Proposed

## Context

Mira exists to be copied: it is a reference implementation whose value is measured by how cheaply
a new domain agent can be stood up next to the `research` and `finance` demos. Today a new
specialist is created by hand — copy a subgraph, register it with the ADR-014 supervisor, author
an ADR-035 agent card, request an ADR-034 identity, and (if the author remembers) add golden
evals. Every manual step is a place where a new agent ships without the invariants the platform
depends on.

The open question is how new domain agents are generated from a spec with the non-negotiables
wired at creation: a per-agent identity (so ADR-034 task-scoped tokens work from the first
dispatch), a published agent card (so the supervisor and future ADR-015 composition can discover
it), a typed tool/skill binding (ADR-031/032), and an eval baseline registered with the ADR-045
CI gate so the agent is gated before it is routable. The spec format, the generation mechanism
(template scaffold vs. generator CLI vs. spec-driven code generation), and how much of the
specialist's graph is generated versus authored are all undecided.

A secondary question is drift: once generated, how does a scaffolded agent stay aligned with
platform upgrades (middleware ordering, containment lint rules, card schema changes) — regenerate,
migrate, or freeze.

## Decision (pending)

This ADR will select the agent scaffolding and generation approach: the agent spec schema, the
generator, and the set of artifacts guaranteed to exist at creation time. It builds on the ADR-014
supervisor registration seam, the ADR-035 agent-card schema, the existing specialist scaffold that
the two demo agents share, ADR-034 identity provisioning, and the ADR-045 eval baseline
registration. The scaffold output must pass the ADR-001/007 containment lint unmodified.

Planned phase: F (dynamic composition, with ADR-015).
