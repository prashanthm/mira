# Model-Tier Routing & Model-Tier Escalation — Plan

> **Feature slug:** model-tier-routing · Sibling spec: [`spec.md`](./spec.md) · Tasks: [`tasks.md`](./tasks.md)

## Depends On

| Dependency | Status | Notes |
|------------|--------|-------|
| ADR-010 / ADR-011 gateway + router | Implemented (router dormant) | This feature wires it |
| ADR-038 / ADR-045 structural checks | Implemented (`mira_harness.policy`/`scoring`) | Reused as the trigger |
| ADR-047 flag mechanism (`ENABLE_*`) | Implemented (`config/profiles.py`) | Gates the wrapper |
| ADR-049/050 decisions vocabulary + harness placement | Implemented | `Decision(kind="escalation")` exists |
| ADR-052 | Accepted | This feature |

## Files

### Create

| Path | Purpose |
|------|---------|
| `src/mira/model/tiering.py` | `ModelTier`, `TIER_ORDER`, `next_tier_up`, `classify_difficulty`, `TierPolicy` |
| `src/mira_harness/quality.py` | `EscalationTrigger` over groundedness / bounds / trace score |
| `src/mira/orchestration/tier_escalation.py` | `TierEscalatingSpecialist` RoutableAgent decorator |
| `tests/test_tiering.py`, `tests/test_quality.py`, `tests/test_tier_escalation.py` | Coverage |

### Modify

| Path | Change |
|------|--------|
| `src/mira/model/routing.py` | `ModelRoute.tier` + tier partition in `Router.select` |
| `src/mira/model/gateway.py` | `tier_policy=`, `complete(tier=)`, `for_agent()`, `chat()` |
| `src/mira/orchestration/agent_cards.py` | `AgentCard.model_hint` + `card_for_domain` threading + `RoutableAgent` context widening |
| `src/mira/orchestration/specialists/demo.py`, `specialists/advisor.py`, `orchestration/foreign.py` | Card tier hints |
| `src/mira/orchestration/specialist_scaffold.py`, `orchestration/contracts_bridge.py` | `SpecialistResult.decisions` + bridge mapping |
| `src/mira/app.py` | `_gateway_from_env` (`MODEL_ROUTES`/`MODEL_ROUTING_STRATEGY`), `for_agent("general")`, flag-gated wrapping |
| `tests/test_routing.py`, `tests/test_gateway*.py`, `tests/test_agent_cards.py`, `tests/test_app.py`, `tests/test_contracts_bridge.py` | Extensions |
