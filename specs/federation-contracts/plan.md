# Federation Contracts & Harness Extraction — Plan

> **Feature slug:** federation-contracts · Sibling spec: [`spec.md`](./spec.md) · Tasks: [`tasks.md`](./tasks.md)

## Depends On

| Dependency | Status | Notes |
|------------|--------|-------|
| ADR-049 Public Envelope & Trace Contracts | Accepted | The two document contracts |
| ADR-050 In-Repo Federation Extraction | Accepted | Package layout, import direction, shim policy |
| ADR-012 / ADR-031 / ADR-036–038 / ADR-042 / ADR-045 | Accepted | The planes being extracted |

## Files

### Create

| Path | Purpose |
|------|---------|
| `src/mira_contracts/{__init__,envelope,trace,agent,tooling}.py` | Contracts package (ADR-049) |
| `src/mira_contracts/schemas/{execution_envelope,trace_result}.v1.json` | Wire-level JSON Schemas |
| `src/mira_harness/{__init__,policy,cost,scoring,gate,versioning}.py` | Governance & improvement planes (ADR-050) |
| `src/mira/orchestration/contracts_bridge.py` | Internals ⇄ contracts adapters |
| `tests/test_contracts_envelope.py`, `tests/test_contracts_trace.py`, `tests/test_contracts_bridge.py`, `tests/test_harness_shims.py` | New coverage |
| `tests/fixtures/lint/bad_harness_imports_mira/`, `bad_contracts_imports_harness/`, `harness_orchestration_dir/` | Linter fixtures |

### Modify (shims / wiring)

| Path | Change |
|------|--------|
| `src/mira/model/versioning.py`, `src/mira/model/cost_attribution.py`, `src/mira/tools/contract.py`, `evals/trace_scoring.py` | Become re-export shims |
| `src/mira/core/guardrails.py` | Keeps middleware + `build_guarded_pipeline`; re-exports detectors from `mira_harness.policy` |
| `evals/regression_gate.py` | Mira wiring over `mira_harness.gate`; `eval_gate()` unchanged |
| `tools/lint_imports.py`, `Makefile`, `pyproject.toml`, `tests/test_lint_imports.py` | New boundary rules, scan roots, package data |

## Order

Contracts package → bridge → extractions (versioning+scoring, tooling, policy+cost, gate),
each landing with `make lint && make test && make eval` green.
