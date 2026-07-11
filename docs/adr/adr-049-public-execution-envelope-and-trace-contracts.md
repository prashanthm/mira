# ADR-049: Public Execution Envelope & Trace/Result Contracts

## Status

Accepted

## Context

Mira's internal task shape is spread across `ReasoningState` / `SupervisorState` TypedDicts, the
`ReasoningBudget` ceilings (ADR-013), and the de facto result contract
`SpecialistResult.to_dict()` — the dict shape every governance consumer already reads: trace
scoring (ADR-045), the regression gate (ADR-012/045), the groundedness and topic-drift checkers
(ADR-038), and the decision-trace store (ADR-040). None of these shapes is public: they are
implementation details of `orchestration/`, so nothing outside Mira can produce or consume them.

The federation direction (ADR-050) requires two agent-agnostic, versioned, serializable
contracts: a task input (**Execution Envelope**) and a task output (**Trace/Result**), so that
Mira's governance and improvement planes can front agents that are not Mira — and so Mira itself
can one day run under an external harness without translation loss.

## Decision Drivers

1. **Agent-agnosticism** — the contracts must be producible/consumable with zero Mira imports.
2. **Internal compatibility** — existing internals must keep working unmodified; internals adapt
   *to* the contracts via a bridge, never the reverse.
3. **Fail-closed validation** (ADR-031/036 discipline) — an out-of-contract document is a
   structured error, never a silent coercion.
4. **No new dependencies** — `jsonschema` is already a core dep; the core stays light (ADR-007).
5. **Existing precedent** — `CARD_SCHEMA_VERSION = "1"` (ADR-035) already establishes the
   string-versioned-schema convention.

## Decision

Ship a new top-level package **`mira_contracts`** (layout decided in ADR-050) containing exactly
two versioned document contracts plus the runner Protocol that connects them:

- **`ExecutionEnvelope` v1** (`mira_contracts/envelope.py`) — `envelope_version` (required,
  `"1"`), `task_id`, `correlation_id` (ADR-040 vocabulary), `tenant` (ADR-042 axis),
  `objective` (required; generalizes `query`), `context_refs` (references, never payloads),
  `constraints` (`require_hitl`, `allow_destructive`, `max_iterations`, `disallowed`),
  `tool_grants` (name-prefix + entitlement pairs; **empty grants = no tools, fail-closed**,
  mirroring `SpecialistSubgraph`'s no-tools branch and ADR-041 token narrowing), `budget`
  (`BudgetSpec` — the `ReasoningBudget` ceilings verbatim, same defaults), and
  `success_criteria` (generalizes golden-case `expect` plus the ADR-045 minimum trace score).
- **`TraceResult` v1** (`mira_contracts/trace.py`) — `trace_version` (required, `"1"`),
  `task_id`/`correlation_id` echo, `agent` (name/kind/version), `status`
  (`ok|error|bound_exceeded|paused`), `answer` (**preserving the recursive
  `provenance{source_type, source_id}` grounding rule** so ADR-038/045 checkers apply
  unmodified), `events` (`plan_step` entries byte-compatible with today's `plan_steps`),
  `decisions`, `costs` (`CostRecord` with an explicit `self_reported` flag), `budget_consumed`,
  `bound_exceeded` (verbatim `asdict(BoundExceeded)`), and `error`.
- **`EnvelopeRunner`** (`mira_contracts/agent.py`) — the synchronous Protocol
  (`card() -> dict`, `run(envelope) -> TraceResult`) any agent implements to be governable.

**Dual representation.** Frozen dataclasses with `to_dict()`/`from_dict()` are the code contract
(repo convention); checked-in JSON Schema files (`schemas/execution_envelope.v1.json`,
`schemas/trace_result.v1.json`, validated with `Draft202012Validator`) are the wire contract.
`validate_envelope()` / `validate_trace()` are fail-closed: unknown or missing version, or any
schema violation, raises `ContractViolation`.

**Versioning.** Additive-optional changes stay within a version; a breaking change ships
`*.v2.json` alongside v1 plus an explicit adapter. Validators never silently coerce.

**Deliberate byte-compatibility.** The `answer`, `events`, and `bound_exceeded` shapes match
`SpecialistResult.to_dict()` field-for-field. This is the mechanism that lets the governance
plane (groundedness, drift, scoring, gate, decision traces) apply to foreign traces with zero
changes — compatibility is the feature, not an accident.

Alternatives considered: adopting A2A Task/Artifact wholesale (rejected for now — heavier
surface than needed; card shapes stay A2A-compatible per ADR-035 so convergence remains open),
and Pydantic models (rejected — `jsonschema` is already the validation dep; core stays light).

## Consequences

- Any agent that can emit a valid `TraceResult` gets Mira's scoring, groundedness, gating, and
  cost attribution for free; any harness that can build an `ExecutionEnvelope` can drive a
  Mira-governed agent.
- Internals translate at one seam (`orchestration/contracts_bridge.py`, ADR-050) — drift between
  internal shapes and public contracts surfaces as bridge test failures, not runtime surprises.
- Budgets in the envelope are *declarative*; enforcement strength varies by adapter (measured
  for Mira-native runs, self-reported or wall-clock-bounded for foreign runs — ADR-051 records
  the honest gap).

## Applies To

`src/mira_contracts/` (new), `src/mira/orchestration/contracts_bridge.py` (new),
`evals/` (consumes `success_criteria` semantics).

## Links

- [ADR-050](./adr-050-in-repo-federation-extraction.md) — package layout & extraction
- [ADR-051](./adr-051-foreign-agent-adapter-experiment.md) — first foreign consumer
- [ADR-013](adr-list.md), [ADR-031](adr-list.md), [ADR-035](adr-list.md),
  [ADR-038](adr-list.md), [ADR-040](adr-list.md), [ADR-045](adr-list.md)
