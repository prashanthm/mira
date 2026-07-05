# ADR-016: Agent Scaffolding & Generation

## Status

Accepted

## Context

Mira exists to be copied: it is a reference implementation whose value is measured by how cheaply
a new domain agent can be stood up next to the `research` and `finance` demos. Before this
decision a new specialist was created by hand — copy a subgraph, register it with the ADR-014
supervisor, author an ADR-035 agent card, request an ADR-034 identity, and (if the author
remembered) add golden evals. Every manual step is a place where a new agent ships without the
invariants the platform depends on.

The open question was how new domain agents are generated with the non-negotiables wired at
creation: a per-agent identity boundary (so ADR-034 task-scoped tokens work from the first
dispatch), a published agent card (so the supervisor and ADR-015 composition can discover it), a
typed tool binding with fail-closed entitlements (ADR-031/032), and an eval baseline registered
with the ADR-045 CI gate so the agent is gated before it is routable. The generation mechanism
(template scaffold vs. generator CLI vs. spec-driven code generation) and how much of the
specialist's graph is generated versus authored were undecided.

A secondary question is drift: once generated, how does a scaffolded agent stay aligned with
platform upgrades (middleware ordering, containment lint rules, card schema changes).

## Decision Drivers

1. **MIRA-SCAFFOLD** — a new domain agent must be cheap to stand up and impossible to stand up
   *without* the platform invariants.
2. **Invariants at creation, not review time** — fail-closed entitlements, DomainSpec allow-lists,
   card publication, and the eval baseline must exist in the generated output, not a checklist.
3. **The scaffold output must pass the ADR-001/007 containment lint unmodified** — generated code
   is subject to the same import-isolation CI as hand-written code.
4. **Offline determinism (ADR-045)** — generation and the generated tests must run with no network
   and no model, so the generator itself is CI-testable.
5. **The shared specialist scaffold already exists** — two demo agents prove
   `build_specialist_subgraph` is the reusable unit; generation should emit *instantiations* of
   it, never new graph wiring.

## Decision

Adopt a **template-scaffold generator CLI**: `mira-scaffold` (console script →
`mira.scaffold:main`, implementation `src/mira/scaffold.py`), generating from string templates
embedded in the module — no external template files, no network, no model.

**1. The command and its guaranteed artifact set**

`mira-scaffold new-domain <name> --tool-prefix <p> [--out DIR] [--domain-kind connector|mcp]`
generates, in one shot:

- `src/mira/connectors/<name>.py` — a `SourceConnector`-conformant skeleton with one functional
  sample capability and `tool_specs()` publishing `<p>`-prefixed tools with **fail-closed
  entitlements** (`connector:<source>:<capability>`; ADR-020/031). With `--domain-kind mcp` the
  connector is skipped and the specialist module instead documents binding the domain to the
  declared MCP server registry (`MCP_SERVERS` env, `mira.connectors.mcp_registry`).
- `src/mira/orchestration/specialists/<name>.py` — a `DomainSpec` (the ADR-034 identity/allow-list
  boundary), a `REPRESENTATIVE_<NAME>_QUERY` placeholder, a `query_inference` hook stub, and
  `build_<name>_specialist()` over the shared `build_specialist_subgraph` — **no new LangGraph
  wiring**. The module docstring carries the ADR-035 **agent-card snippet and registration
  instructions**, so discovery wiring is copy-paste, not archaeology.
- `tests/test_<name>_connector.py` + `tests/test_<name>_specialist.py` — minimal tests that
  **pass over the skeleton as generated**: protocol conformance, prefixed entitlement-bearing
  tool export, DomainSpec identity, and the empty-allowlist / cross-domain fail-closed
  invariants. A scaffolded agent is born tested.
- `specs/<name>-specialist/{spec,plan,tasks}.md` — the spec trio in the repo's established shape,
  with TODO seams where domain behaviour goes.
- `evals/goldens/<name>.jsonl.example` — the ADR-045 golden stub; promoted (renamed to `.jsonl`)
  once the representative query answers end-to-end, so the agent is **eval-gated before it is
  routable**.

**2. Safety properties of generation**
- **Refuses to overwrite**: if any target path exists, nothing is written and the command fails
  loudly — generation is all-or-nothing.
- Generated output passes the import-isolation lint and the sanitize gate unmodified (asserted by
  `tests/test_scaffold.py`, which also runs the *generated* tests via a subprocess pytest against
  the generated tree).

**3. Drift stance: scaffolded agents are code, not derived artifacts**
- After generation the agent is ordinary hand-maintained code: platform upgrades land on it via
  ordinary refactors, exactly as they land on `research`/`finance`. The templates version with
  the platform, so regeneration into a scratch tree gives a diffable "current best practice"
  reference; the refuse-to-overwrite rule makes regeneration compare-then-merge, never clobber.

**Rejected alternatives:**

- **Spec-driven full code generation (agent graph generated from a schema)** — Rejected: the
  shared specialist scaffold already reduces a domain to a `DomainSpec` + tool binding + one hook;
  generating graph code would create a second authoring path to keep aligned with the scaffold it
  duplicates.
- **Copy-by-hand from the demo agents (no generator)** — Rejected: the status quo this ADR
  closes; every manual step is an invariant that can silently not ship (no card, no eval baseline,
  no fail-closed entitlement).

**Deferred:**
- Automatic identity **provisioning** against a real IdP at generation time — the generated
  `DomainSpec` is the ADR-034 scope boundary, and the in-process `TokenExchanger` covers it today;
  IdP registration is deployment wiring.
- Automatic golden **promotion** — the stub is deliberately `.jsonl.example`; a golden only gates
  CI once a human confirms the representative query answers end-to-end.

## Consequences

### Becomes Easier

- A new domain is one command away from a compiling, tested, lint-clean, discoverable skeleton —
  the reference implementation's "cheap to copy" claim is executable.
- The invariants ship in the artifact, not the review: entitlements are fail-closed, the
  allow-list exists, the card snippet is in the module, the eval stub exists.
- The generator is itself CI-gated (`tests/test_scaffold.py` runs generated tests + sanitize
  checks), so template rot fails the build, not the next user.

### Becomes Harder

- Templates are a second place platform conventions live; a convention change must update the
  templates and their assertions or the scaffold drifts from the demos (mitigated by the
  scaffold test running generated output against the real platform modules).
- The `--domain-kind mcp` path generates documentation-plus-specialist, not a turnkey MCP binding —
  the remote-tool wiring remains a manual step at deployment.
- Refuse-to-overwrite means regeneration cannot update in place; keeping a scaffolded agent
  current is a merge activity, by design.

## Applies To

- **MIRA-SCAFFOLD** — primary; the generator and its guaranteed artifact set.
- **MIRA-AGENTS** — generated specialists register into ADR-014 routing like the demos.
- [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) /
  [ADR-007](./adr-007-core-agent-stack-and-framework.md) — generated output passes containment lint unmodified.
- [ADR-014](./adr-014-domain-agent-supervisor-routing.md) — the registration seam generated agents wire into.
- [ADR-015](./adr-015-dynamic-workflow-composition.md) — a scaffolded agent is composable once its card registers.
- [ADR-020](./adr-020-source-connector-architecture.md) / [ADR-031](./adr-031-typed-tool-contracts.md) —
  the connector shape and fail-closed typed tool contracts the templates emit.
- [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md) /
  [ADR-035](./adr-035-agent-cards-and-a2a-discovery.md) — identity boundary + card wired at creation.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — the golden stub is the eval-gated-before-routable hook.

## Links

- ADR file: `docs/adr/adr-016-agent-scaffolding-and-generation.md`
- Implementation: `src/mira/scaffold.py` (console script `mira-scaffold`); tests `tests/test_scaffold.py`
- Catalog: [adr-list.md](./adr-list.md) — ADR-016
- Epic: MIRA-SCAFFOLD
