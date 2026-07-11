# ADR-052: Per-Agent Model Tiers & Quality-Triggered Model-Tier Escalation

## Status

Accepted

## Context

Mira's model layer treats every call identically: `Router` (ADR-011) ranks routes by
cost/latency/quota only — it never looks at the *question* or at *which agent* is asking —
and the composition root never constructs a router at all, so the machinery is dormant.
Meanwhile the platform is a graph of specialists with unequal model needs: a keyword-routed
demo domain needs nothing, a general reasoning turn needs a capable chat model, an advisory
synthesis benefits from a reasoning-grade model. With one endpoint serving multiple models
(e.g. a `deepseek-chat` / `deepseek-reasoner` pair behind one `LLM_BASE_URL`), the per-call
`model=` override already exists — what is missing is the decision of *which* model, per
agent and per question.

Two constraints shape the design. First, offline determinism (ADR-045): tests and evals
never call a model, so difficulty classification must be structural, not model-graded.
Second, ADR-039 owns the word "escalation" for HITL — this ADR's mechanism is always named
**model-tier escalation**.

A latent gap surfaced during design: `Gateway` exposes `complete` but not `chat`, so
`GatewayChatModel` (`orchestration/model_adapter.py`) probes `getattr(llm, "chat", None)`,
finds nothing on the gateway, and silently downgrades tool selection to a text completion.
Any routed model would therefore never apply to the tool-calling path. This ADR closes that
gap so routing is coherent across both call shapes.

## Decision Drivers

1. **Per-agent fit** — not all agents need the same model; the declaration belongs on the
   agent card (discovery metadata), not in core code.
2. **Question-aware selection** — cheap models for cheap questions, deterministic and
   offline-testable.
3. **Budget supremacy** (ADR-011/042) — capability preferences never override budget caps.
4. **Opt-in, byte-identical defaults** — like the router/fallback wiring, nothing changes
   for deployments that don't configure it.
5. **Auditability** (ADR-040/049) — a tier escalation is a recorded decision with cost
   spans, not silent behavior.

## Decision

**Tier is route data + a gateway policy; the agent card declares a hint; a deterministic
heuristic covers un-hinted questions; quality failures trigger exactly one dispatch-level
retry on a stronger tier.**

- `mira.model.tiering` (new, stdlib-only): `ModelTier` (`light|standard|deep`),
  `TIER_ORDER`, `next_tier_up()`, the pure `classify_difficulty()` heuristic (explicit
  `:tool:` calls short-circuit to `light`; length, multi-part shape, analytic markers, and
  cross-domain keyword hits add points; thresholds are module constants), and `TierPolicy`
  with resolution precedence **explicit > agent hint > heuristic > default**.
- `ModelRoute.tier: str = ""` and `Router.select(..., tier=None)`: after strategy ranking,
  tier-matching routes are stably partitioned first; a missing tier falls back to the full
  ranking (never fails on capability); the budget gate then runs over that ordering and the
  downgrade search spans the **full** ranked list — budget beats capability by construction.
  No new `RoutingStrategy`: tier is a preference orthogonal to ranking.
- `Gateway(bundle, ..., tier_policy=None)`, `complete(..., tier=None)`, and
  `Gateway.for_agent(name)` — a bound `ILLMProvider` view that forwards agent identity so
  call sites that only know the protocol still get per-agent resolution. **New
  `Gateway.chat(...)`** routes and emits spans exactly like `complete` and delegates to the
  backend's `chat` when present (the echo bundle has none, so offline paths are unaffected).
- `AgentCard.model_hint: str = ""` — a **tier name**, never a model id, so cards stay
  deployment-agnostic; the tier→model mapping is environment configuration
  (`MODEL_ROUTES` JSON + optional `MODEL_ROUTING_STRATEGY`, parsed in the composition root;
  absent ⇒ today's `Gateway(bundle)` exactly).
- **Model-tier escalation**: `mira_harness.quality.EscalationTrigger` (agent-agnostic;
  reuses `GroundednessChecker` and `score_trace`; stable reasons `ungrounded_answer`,
  `bound_exceeded`, `low_trace_score`) + `mira.orchestration.tier_escalation.
  TierEscalatingSpecialist`, a `RoutableAgent` decorator in the `ForeignSpecialist` style:
  one retry maximum, on `next_tier_up`, with `context={"model_tier": ...}` and an isolated
  thread id; the retry is kept only if its trace score improves; `BudgetExceeded` on the
  retry keeps the first result (reason `budget`). The wrapper appends a
  `{"kind": "escalation"}` decision to the new `SpecialistResult.decisions` field, which the
  contracts bridge maps to `TraceResult.decisions` (an existing `DECISION_KINDS` value — no
  schema change). Wrapping is registration-time and double-flagged: tier routing configured
  **and** `ENABLE_TIER_ESCALATION` (ADR-047 flag mechanism); the eval registry never wraps.

DeepSeek reference configuration:

```bash
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat
export MODEL_ROUTES='[
  {"provider": "deepseek", "model": "deepseek-chat", "tier": "light", "cost_per_1k_tokens": 0.00028},
  {"provider": "deepseek", "model": "deepseek-reasoner", "tier": "deep", "cost_per_1k_tokens": 0.0022}]'
export ENABLE_TIER_ESCALATION=1
```

## Consequences

- Agents declare what they need; questions upgrade themselves deterministically; budgets
  still win; every upgrade is auditable (decision record + two cost spans).
- The `Gateway.chat` passthrough *enables previously dead behavior*: with a live provider,
  tool selection now actually routes through the gateway instead of silently degrading to
  text. Offline tests/evals are unaffected (echo provider has no `chat`).
- The heuristic is intentionally crude and structural; a model-graded classifier stays out
  of the default path and belongs to the live-provider eval profile (ADR-045 split).
- Terminology fence: "escalation" unqualified = ADR-039 HITL; this mechanism is always
  "model-tier escalation" in code and docs.

## Applies To

`src/mira/model/{tiering,routing,gateway}.py`, `src/mira/orchestration/{agent_cards,
tier_escalation,contracts_bridge,specialist_scaffold}.py`, `src/mira_harness/quality.py`,
`src/mira/app.py`, `src/mira/config/profiles.py` flags.

## Links

- [ADR-010](adr-list.md) model gateway · [ADR-011](adr-list.md) routing & budget caps
- [ADR-038](adr-list.md)/[ADR-045](adr-list.md) structural quality checks the trigger reuses
- [ADR-039](adr-list.md) HITL escalation (distinct) · [ADR-047](adr-list.md) flag mechanism
- [ADR-049](./adr-049-public-execution-envelope-and-trace-contracts.md)/[ADR-050](./adr-050-in-repo-federation-extraction.md) decision vocabulary & harness placement
