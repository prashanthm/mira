# Foreign Specialist Adapter — Plan

> **Feature slug:** foreign-specialist · Sibling spec: [`spec.md`](./spec.md) · Tasks: [`tasks.md`](./tasks.md)

## Depends On

| Dependency | Status | Notes |
|------------|--------|-------|
| ADR-049 / ADR-050 (federation-contracts feature) | Accepted | Contracts + extracted planes |
| ADR-051 Foreign-Agent Adapter Experiment | Accepted | This feature |
| ADR-014 / ADR-035 supervisor + agent cards | Implemented | Registration surface |

## Files

### Create

| Path | Purpose |
|------|---------|
| `src/mira_harness/stub_agent.py` | Deterministic offline foreign `EnvelopeRunner` |
| `src/mira_harness/cli_adapter.py` | Generic subprocess adapter (optional/flagged) |
| `src/mira/orchestration/foreign.py` | `ForeignSpecialist` wrapper, `foreign_card`, `register_foreign_stub` |
| `evals/goldens/foreign.jsonl` | Foreign golden cases |
| `tests/test_stub_agent.py`, `tests/test_foreign_specialist.py`, `tests/test_cli_adapter.py`, `evals/test_foreign_evals.py` | Coverage |

### Modify

| Path | Change |
|------|--------|
| `src/mira/orchestration/agent_cards.py` | `RoutableAgent` Protocol; factory/resolve widened (behavior-neutral) |
| `evals/conftest.py` | Shared `build_eval_registry()` (demo + foreign stub) |
| `evals/regression_gate.py` | Default registry includes the foreign stub |
| `evals/test_golden_functional.py` | Golden-count floor bump |
| `src/mira/app.py` | Env-flagged `FOREIGN_AGENT_CMD` wiring |

## Experiment closure

Answers to ADR-051's seven empirical questions get recorded in ADR-051 → Consequences.
