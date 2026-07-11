# ADR-051: Foreign-Agent Adapter Experiment

## Status

Accepted

## Context

ADR-049/050 make Mira's governance planes agent-agnostic on paper. The open empirical question
is whether **envelope normalization is tractable in practice**: can an agent that is not Mira
run under Mira's supervisor, policy, cost attribution, and eval gate — through the public
contracts alone — without per-agent special cases leaking into the core? The federation
strategy's next phase depends on the answer, so we buy the answer with exactly one adapter.

## Decision Drivers

1. **Empiricism over speculation** — one real adapter, driven end-to-end through the existing
   supervisor and eval gate, answers what design review cannot.
2. **Offline CI** (ADR-045) — the experiment must run with no network, keys, or vendor SDKs,
   in the spirit of the `local` echo provider (ADR-002).
3. **No supervisor surgery** (ADR-014/035) — registration must be the same
   `registry.register(card, factory)` call a native specialist uses.
4. **Fail-closed governance** (ADR-036) — a misbehaving foreign agent degrades to a structured
   error, never a crash, and is policy-checked *before* it runs.

## Decision

Wrap exactly **one** foreign agent as a routable specialist:

- **`StubEchoAgent`** (`mira_harness/stub_agent.py`) — a deterministic, offline
  `EnvelopeRunner` that imports **only `mira_contracts`** (a test asserts no `mira` import —
  the agent-agnosticism proof). It answers from the envelope's objective with
  provenance-carrying claims, emits plan/act/observe `plan_step` events, reports honest
  `budget_consumed` and a zero-cost `CostRecord` flagged `self_reported`, and returns
  `status="bound_exceeded"` when handed a zero-step budget (a budget-conformance probe).
- **`ForeignSpecialist`** (`src/mira/orchestration/foreign.py`) — makes any `EnvelopeRunner`
  routable. Its `invoke(query, *, thread_id)` pipeline is fail-closed at every step:
  policy-in (`InjectionDetector` runs *before* the foreign agent is ever called) → build +
  `validate_envelope` via `contracts_bridge` → `runner.run()` with exceptions wrapped to a
  structured error → `validate_trace` (an out-of-contract trace becomes an error result) →
  foreign `CostRecord`s recorded into the injected `CostLedger` as
  `AttributedSpan(domain=...)` → conversion to `SpecialistResult`. From that point the whole
  existing governance surface (groundedness, drift, decision traces, `/explain`) applies
  unchanged, because the dict shape is the one those components already consume.
- **Registration via agent cards** — a `foreign_card()` helper plus
  `register_foreign_stub(registry)`; the supervisor is untouched. The only enabling change is
  widening the registry's factory type to a `RoutableAgent` Protocol
  (`invoke(query, *, thread_id) -> SpecialistResult`) in `agent_cards.py`, which
  `SpecialistSubgraph` already satisfies (behavior-neutral).
- **Eval coverage** — `evals/goldens/foreign.jsonl` joins the golden set; the shared eval
  registry (`build_eval_registry()`) registers the foreign stub for both the pytest evals and
  the `run_gate()` default. The foreign specialist is therefore held to the same structural
  bar (trace score 1.0) and **ADR-012 promotions are gated on it** — a foreign-adapter
  regression blocks promotion by design.
- **`CliAgentAdapter`** (`mira_harness/cli_adapter.py`, optional) — the generic cross-process
  shape: envelope JSON on stdin, one trace JSON document on stdout, injected argv + timeout
  (the timeout doubles as harness-side wall-clock budget enforcement). Any failure (non-zero
  exit, timeout, bad JSON, invalid trace) returns `TraceResult(status="error")`, never raises.
  CI exercises it subprocess-of-self (`sys.executable -c …`), offline. Service wiring is
  env-flagged (`FOREIGN_AGENT_CMD`); absent flag ⇒ zero behavior change.

**Honest limitation recorded up front:** envelope budgets are advisory for foreign agents — a
foreign agent can misreport `budget_consumed`/`costs`. Harness-side enforcement is limited to
the CLI adapter's wall-clock timeout; the `self_reported` cost flag exists so downstream
consumers can weigh trust accordingly.

## Empirical Questions (answers recorded in Consequences when the experiment lands)

1. Can a non-Mira agent satisfy the recursive provenance grounding rule, or does Trace v2 need
   a foreign-friendly citations alternative?
2. Do enforced (native), self-reported (stub), and externally-bounded (CLI timeout) budgets fit
   one `BudgetSpec`/`BudgetConsumed` shape?
3. Are `name_prefix` + entitlement tool grants meaningful across a process boundary, or do
   grants need MCP endpoint references to be actionable?
4. Is the `plan_step` event vocabulary expressive enough for non-ReAct reasoning styles to earn
   `has_plan`, or does `score_trace` over-index on Mira's loop shape?
5. Can self-reported foreign costs blend with gateway-measured native costs in one ledger
   without corrupting anomaly detection?
6. Where do contract violations surface best — pre-dispatch (envelope), post-run (trace), or
   supervisor synthesis?
7. How much normalization glue does one adapter actually require — the tractability number the
   next federation phase depends on.

## Consequences

- One foreign agent runs under supervisor routing, policy-in, cost attribution, groundedness,
  trace scoring, and the promotion gate, with the supervisor unchanged — or we learn precisely
  which contract assumption breaks.
- The golden gate gets stricter: a foreign-stub bug blocks ADR-012 promotions. Intentional —
  that is federation governance working; a one-line registry change removes it if needed.
- *(To be filled by the experiment write-up: answers to the seven questions above.)*

## Applies To

`src/mira_harness/stub_agent.py`, `src/mira_harness/cli_adapter.py`,
`src/mira/orchestration/foreign.py`, `src/mira/orchestration/agent_cards.py`,
`evals/goldens/foreign.jsonl`, `evals/conftest.py`, `evals/regression_gate.py`.

## Links

- [ADR-049](./adr-049-public-execution-envelope-and-trace-contracts.md),
  [ADR-050](./adr-050-in-repo-federation-extraction.md)
- [ADR-002](adr-list.md), [ADR-012](adr-list.md), [ADR-014](adr-list.md),
  [ADR-035](adr-list.md), [ADR-036](adr-list.md), [ADR-045](adr-list.md)
