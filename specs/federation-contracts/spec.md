# Federation Contracts & Harness Extraction — Spec

> **Feature slug:** federation-contracts
> Siblings: [`plan.md`](./plan.md) (files/steps/ADRs) · [`tasks.md`](./tasks.md) (granular units + Loop AC)

## Behavior / What

Publish Mira's task input/output shapes as **two versioned, agent-agnostic public contracts**
(`ExecutionEnvelope` v1, `TraceResult` v1 — ADR-049) and extract the **governance & improvement
planes** behind them into top-level packages `mira_contracts` and `mira_harness` (ADR-050), so
any agent — not just Mira — can adopt policy detection, cost attribution, trace scoring, the
regression gate, and eval-gated versioning. Internals adapt to the contracts through
`orchestration/contracts_bridge.py`; nothing existing breaks.

### Observable behaviors

1. **Contracts** — `mira_contracts.envelope`/`.trace` round-trip through
   `to_dict()/from_dict()`; `validate_envelope()`/`validate_trace()` are fail-closed
   (`ContractViolation` on unknown version or schema violation); JSON Schemas ship as package
   data and agree with the dataclasses.
2. **Bridge fidelity** — `SpecialistResult → TraceResult → SpecialistResult` reproduces
   `to_dict()` byte-for-byte; `BudgetSpec ⇄ ReasoningBudget` preserves all four ceilings.
3. **Extraction with shims** — versioning, trace scoring, tool contracts, guardrail detectors,
   cost attribution, and the generic gate live in the new packages; every old import path still
   works (re-export shims, `old.X is new.X`).
4. **Boundary enforcement** — `make lint-imports` scans all three src roots and fails on any
   `mira.*` import inside the new packages, or `mira_harness` import inside `mira_contracts`.
5. **Unchanged gates** — `make test` and `make eval` pass with the pre-existing test files
   unmodified.
