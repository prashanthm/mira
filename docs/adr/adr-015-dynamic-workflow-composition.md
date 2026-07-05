# ADR-015: Dynamic Workflow Composition

## Status

Accepted

## Context

Mira's ADR-014 supervisor routes requests to statically registered domain specialists (the
`research` and `finance` demo agents), each a state-isolated LangGraph subgraph discoverable via
an ADR-035 agent card. Routing today is a fixed decision: the supervisor picks one specialist per
dispatch. As the number of agents and ADR-032 skills grows, the interesting requests are the ones
no single specialist covers — e.g. "summarize the design notes that explain last quarter's spend
anomaly" spans both the Markdown-docs corpus and the CSV ledger.

The open question was how multi-step workflows get composed from discoverable agents and skills at
request time rather than hardcoded at build time. Candidate directions ranged from
supervisor-planned workflows (an explicit plan over agent cards, executed on the existing dispatch
paths) to emergent handoff patterns where agents delegate to one another directly. Each direction
has different implications for the single auditable control flow, hierarchical failure boundaries,
and loop-safety bounds that ADR-013 and ADR-014 committed to.

Composition also interacts with identity and governance: ADR-034 mints a task-scoped token per
specialist dispatch, so a composed workflow multiplies token-minting events and must keep each
step within the narrowest scope that step needs. Any composition mechanism must preserve
per-step attribution in decision traces (ADR-040) and remain evaluable by the ADR-045 CI gate.

## Decision Drivers

1. **MIRA-COMPOSE** — multi-step workflows over discoverable agents, building on ADR-014 routing.
2. **Single auditable control flow (ADR-014)** — composition must not introduce a second control
   plane; a regulated setting needs one traceable plan → dispatch → synthesis path.
3. **Discovery-driven (ADR-035)** — plans are built from agent cards, never a hard-wired roster;
   adding a domain must extend the composable set with zero composer changes.
4. **Determinism for the eval gate (ADR-045)** — a composed plan must be reproducible offline so
   goldens can gate it; model-driven planning layers on later behind the same seam.
5. **Least-privilege per step (ADR-034)** — each step executes as one ordinary specialist dispatch,
   so per-dispatch token scoping applies unchanged.

## Decision

Adopt **supervisor-planned composition**: a `WorkflowComposer`
(`src/mira/orchestration/composition.py`) plans an explicit, inspectable sequence of
`WorkflowStep`s over the ADR-035 agent-card registry and executes it entirely on the ADR-014
supervisor's existing dispatch paths.

**1. Plan representation**
- `WorkflowStep` (frozen): target `domain`, `query` (the sub-task), and a human-readable
  `rationale` recording *why* the step was planned — the plan itself is audit evidence.
- `ComposedWorkflow`: the step tuple plus executed results (the ADR-014
  `SpecialistResult` dict contract, unchanged) and the synthesized answer.

**2. Deterministic structural decomposition (`compose`)**
- The query is split on explicit sequence seams (`" and then "`, `"; "`) into ordered
  sub-queries; each sub-query is classified against the card registry's deterministic keyword
  matcher (the same classifier the supervisor routes with).
- A sub-query no card matches is kept as a **fallback step** (`domain == ""`) — a plan never
  silently drops work; execution surfaces it as an unmatched (general) result.
- A seamless query that strongly matches **multiple** cards (≥ 1 distinct keyword hit for ≥ 2
  cards) composes one step per matched card — the **parallel fan-out** shape.
- A model-driven planner slots in **behind `compose` later** (deferred): the step contract and
  execution path are fixed; only the decomposition heuristic is replaced. The optional
  ADR-032 `SkillsRegistry` constructor seam is where that planner composes skills (not just whole
  specialists) into steps.

**3. Execution on existing dispatch paths (`execute`)**
- **Single-step plans delegate wholesale to `Supervisor.invoke`** — the composer adds nothing to
  the single-domain path (including the supervisor's general fallback).
- **Parallel plans execute via `Supervisor.fan_out`** — the multi-specialist dispatch ADR-014
  already ships.
- **Sequential plans pipe each step through its composed specialist subgraph** in order; the
  prior step's attributed synthesis line is appended to the next step's query as `[context] ...`,
  so later steps condition on earlier answers while each specialist still sees its own sub-query
  first (per-domain `query_inference` hooks keep working).
- Synthesis reuses the supervisor's per-domain attributed-line style — one `[domain] {...}` line
  per step, errors kept visible — so a composed answer reads identically to a routed one.
- No second control plane: every step is an ordinary specialist dispatch under the same
  middleware pipeline (ADR-009), loop bounds (ADR-013), and result contract as a single-agent
  request; per-dispatch task-scoped tokens (ADR-034) apply per step unchanged.

**Rejected alternatives:**

- **Emergent peer handoff (agents delegate to one another directly)** — Rejected: reintroduces the
  swarm topology ADR-014 already rejected — no single control flow to audit or bound, and
  multi-hop delegation breaks ADR-034's single-hop token-scoping model.
- **Model-planned free-form DAGs now** — Rejected for the first slice: not offline-evaluable, and
  the plan schema would be designed around a planner we don't run yet. The structural composer
  fixes the plan/execution contract; the planner drops in behind `compose` without changing it.

**Deferred (revisit when live model providers are wired):**
- Model-driven planning behind `compose()` (the seam is explicit and tested).
- Skill-aware step planning via the `SkillsRegistry` constructor seam (ADR-032).
- Multi-hop token exchange if steps ever delegate to sub-steps (flagged open in ADR-034).

## Consequences

### Becomes Easier

- Cross-domain requests ("X and then Y", "compare X with Y") execute as inspectable multi-step
  plans with per-step attribution — no hand-written multi-domain glue.
- The plan is data (`WorkflowStep` tuple with rationales): decision traces (ADR-040) and the
  ADR-045 gate can assert on composition itself, not just final answers.
- Adding a domain extends the composable set automatically — composition reads the same card
  registry as routing (ADR-035).

### Becomes Harder

- Structural seam-splitting is deliberately conservative: queries that *imply* multiple domains
  without a seam or shared keywords stay single-routed until the model-driven planner lands.
- Sequential context threading (appending the prior attributed line) is a fixed convention; richer
  inter-step data flow (typed step inputs/outputs) is future work on the same step contract.
- Every composed step is a real specialist dispatch — multi-step plans multiply token/cost
  overhead, so ADR-014's cost discipline (fan out only when justified) applies to plans too.

## Applies To

- **MIRA-COMPOSE** — primary; dynamic composition over ADR-014 routing.
- **MIRA-AGENTS** — composed steps execute the same specialist subgraphs.
- [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) — each step runs under the same loop bounds.
- [ADR-014](./adr-014-domain-agent-supervisor-routing.md) — the supervisor dispatch paths composition executes on.
- [ADR-016](./adr-016-agent-scaffolding-and-generation.md) — scaffolded agents are composable the moment their card registers.
- [ADR-032](./adr-032-skills-registry-versioning-and-authorization.md) — the skills seam future planners compose steps from.
- [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md) — per-step task-scoped dispatch; multi-hop deferred.
- [ADR-035](./adr-035-agent-cards-and-a2a-discovery.md) — agent cards are the discovery metadata plans are built from.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — deterministic composition keeps plans offline-evaluable.

## Links

- ADR file: `docs/adr/adr-015-dynamic-workflow-composition.md`
- Implementation: `src/mira/orchestration/composition.py`; tests `tests/test_composition.py`
- Catalog: [adr-list.md](./adr-list.md) — ADR-015
- Epic: MIRA-COMPOSE
