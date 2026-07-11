# Model-Tier Routing & Model-Tier Escalation — Spec

> **Feature slug:** model-tier-routing
> Siblings: [`plan.md`](./plan.md) · [`tasks.md`](./tasks.md)

## Behavior / What

Route each model call to the tier it deserves (ADR-052): specialists declare a tier hint on
their agent card, un-hinted questions are classified by a deterministic structural heuristic,
and a structurally poor result triggers exactly one retry on the next tier up. Budget caps
always beat capability preferences. Everything is opt-in — with no `MODEL_ROUTES` configured,
the gateway behaves byte-identically to today.

### Observable behaviors

1. **Tier-aware routing** — `Router.select(tier=...)` prefers tier-matching routes after
   strategy ranking; a missing tier falls back to the full ranking; budget downgrade searches
   the full list (budget wins).
2. **Resolution precedence** — `TierPolicy.resolve`: explicit `tier=` arg > agent-card hint >
   `classify_difficulty(query)` > default. Identical input ⇒ identical tier (offline
   determinism).
3. **Per-agent identity** — `Gateway.for_agent(name)` forwards agent identity through the
   `ILLMProvider` seam; general turns route with the heuristic.
4. **Chat-path coherence** — `Gateway.chat` route-selects and emits spans exactly like
   `complete`; tool-calling no longer bypasses routing (echo bundle has no `chat`, offline
   paths unaffected).
5. **Model-tier escalation** — `TierEscalatingSpecialist` retries **once** with
   `context={"model_tier": <next tier>}` on an isolated thread id when
   `EscalationTrigger.check` fires (`ungrounded_answer` / `bound_exceeded` /
   `low_trace_score`); keeps the retry only if its trace score improves; `BudgetExceeded` on
   the retry keeps the first result. Every attempt records a
   `{"kind": "escalation"}` decision in `SpecialistResult.decisions`, which the contracts
   bridge round-trips to `TraceResult.decisions` byte-compatibly.
6. **Flagged wiring** — factories wrap only when tier routing is configured **and**
   `ENABLE_TIER_ESCALATION` is set; the eval registry never wraps, so eval semantics are
   untouched.
