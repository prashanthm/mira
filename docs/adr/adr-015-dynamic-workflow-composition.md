# ADR-015: Dynamic Workflow Composition

Status: Proposed

## Context

Mira's ADR-014 supervisor routes requests to statically registered domain specialists (the
`research` and `finance` demo agents), each a state-isolated LangGraph subgraph discoverable via
an ADR-035 agent card. Routing today is a fixed decision: the supervisor picks one specialist per
dispatch from a hand-maintained roster. As the number of agents and ADR-032 skills grows, the
interesting requests are the ones no single specialist covers — e.g. "summarize the design notes
that explain last quarter's spend anomaly" spans both the Markdown-docs corpus and the CSV
ledger.

The open question is how multi-step workflows get composed from discoverable agents and skills at
request time rather than hardcoded at build time. Candidate directions range from
supervisor-planned DAGs (the supervisor emits an explicit plan over agent cards and skill
contracts, then executes it as a dynamic subgraph) to more emergent handoff patterns where agents
delegate to one another directly. Each direction has different implications for the single
auditable control flow, hierarchical failure boundaries, and loop-safety bounds that ADR-013 and
ADR-014 committed to.

Composition also interacts with identity and governance: ADR-034 mints a task-scoped token per
specialist dispatch, so a composed workflow multiplies token-minting events and must keep each
step within the narrowest scope that step needs. Any composition mechanism must preserve
per-step attribution in decision traces (ADR-040) and remain evaluable by the ADR-045 CI gate.

## Decision (pending)

This ADR will select the composition model — how a multi-step workflow is planned, represented,
executed, and bounded when it spans multiple agents and skills. It builds on the existing seams:
the ADR-014 supervisor (orchestrator-worker over LangGraph subgraphs), ADR-035 agent cards as the
discovery metadata composition plans are built from, ADR-032 skills as the versioned capability
units, and the specialist scaffold that ADR-016 will generate new agents into. It must not
introduce a second control plane: composed workflows execute under the same middleware pipeline
(ADR-009) and loop bounds (ADR-013) as single-agent requests.

Planned phase: F (dynamic composition, with ADR-016).
