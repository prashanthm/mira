# Model-Tier Routing & Model-Tier Escalation — Tasks

> **Feature slug:** model-tier-routing · Spec: [`spec.md`](./spec.md) · Plan: [`plan.md`](./plan.md)

Ordered implementation units.

---

## Task 1 — Model plane

`tiering.py`, `ModelRoute.tier` + tier partition, gateway `tier_policy`/`for_agent`/`chat`.

## Loop AC

- [x] AC-1: heuristic table deterministic; `TierPolicy.resolve` precedence explicit > hint > heuristic > default
  - verify: `pytest tests/test_tiering.py -q`
- [x] AC-2: tier partition + missing-tier fallback + budget-downgrade-crosses-tiers; gateway fast path unchanged; `chat` routes + emits spans
  - verify: `pytest tests/test_routing.py tests/test_gateway.py tests/test_gateway_resilience.py -q`

---

## Task 2 — Per-agent wiring

`AgentCard.model_hint`, card hints, `_gateway_from_env`, runtime `for_agent("general")`.

## Loop AC

- [x] AC-1: absent `MODEL_ROUTES` ⇒ gateway identical to today; present ⇒ router + card-derived TierPolicy; malformed ⇒ raises
  - verify: `pytest tests/test_app.py tests/test_agent_cards.py -q`

---

## Task 3 — Model-tier escalation

`quality.py` trigger, `TierEscalatingSpecialist`, `SpecialistResult.decisions` + bridge, flag wiring.

## Loop AC

- [x] AC-1: each trigger reason fires; grounded/in-bounds/high-score pass through untouched
  - verify: `pytest tests/test_quality.py -q`
- [x] AC-2: exactly one retry with `context={"model_tier": ...}` + isolated thread id; keep-better; budget wins; decision recorded; bridge round-trip stays byte-equal
  - verify: `pytest tests/test_tier_escalation.py tests/test_contracts_bridge.py -q`
