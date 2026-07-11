# Foreign Specialist Adapter — Spec

> **Feature slug:** foreign-specialist
> Siblings: [`plan.md`](./plan.md) · [`tasks.md`](./tasks.md)

## Behavior / What

Wrap exactly **one foreign agent** (an `EnvelopeRunner` that is not Mira) as a
supervisor-routable specialist (ADR-051), to empirically test whether envelope normalization
(ADR-049) is tractable. A deterministic offline stub (`mira_harness.stub_agent.StubEchoAgent`)
is the CI-exercised foreign agent; a generic subprocess CLI adapter is the optional
cross-process shape.

### Observable behaviors

1. **Agent-agnosticism proof** — `stub_agent.py` imports `mira_contracts` only; a test asserts
   no `mira`/`mira_harness`-internal coupling beyond contracts.
2. **Fail-closed wrapper** — `ForeignSpecialist.invoke()` blocks injection queries *before* the
   foreign agent runs; wraps runner exceptions and out-of-contract traces into structured
   `SpecialistResult` errors; never crashes the supervisor graph.
3. **Governed like a native** — foreign costs land in the `CostLedger` under the foreign
   domain; groundedness/drift/scoring apply to the converted result unchanged.
4. **Routing without supervisor changes** — registration is one
   `registry.register(foreign_card(...), factory)`; the only core change is the
   `RoutableAgent` Protocol widening in `agent_cards.py`.
5. **Eval-gated** — `evals/goldens/foreign.jsonl` cases route through the real supervisor to
   the stub and must score 1.0; `eval_gate()` (ADR-012 promotions) now covers the foreign
   adapter.
6. **CLI adapter (flagged)** — envelope JSON in, trace JSON out, timeout-bounded; any failure
   is `TraceResult(status="error")`; absent `FOREIGN_AGENT_CMD` ⇒ zero behavior change.
