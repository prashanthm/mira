# Federation Contracts & Harness Extraction — Tasks

> **Feature slug:** federation-contracts · Spec: [`spec.md`](./spec.md) · Plan: [`plan.md`](./plan.md)

Ordered implementation units.

---

## Task 1 — `mira_contracts` package

Envelope/trace dataclasses + JSON Schemas + fail-closed validation + `EnvelopeRunner` Protocol;
linter/Makefile/pyproject wiring.

## Loop AC

- [ ] AC-1: round-trip + fail-closed validation
  - verify: `pytest tests/test_contracts_envelope.py tests/test_contracts_trace.py -q`
- [ ] AC-2: boundary rules enforced (including the nested-`orchestration`-dir trap)
  - verify: `pytest tests/test_lint_imports.py -q`

---

## Task 2 — Contracts bridge

`ReasoningBudget ⇄ BudgetSpec`, `SpecialistResult ⇄ TraceResult`, `envelope_for_dispatch`.

## Loop AC

- [ ] AC-1: `SpecialistResult → TraceResult → SpecialistResult` is `to_dict()`-byte-equal
  - verify: `pytest tests/test_contracts_bridge.py -q`

---

## Task 3 — Plane extractions with shims

versioning, scoring, tooling, guardrail detectors, cost attribution, generic gate.

## Loop AC

- [ ] AC-1: every old import path re-exports identical objects
  - verify: `pytest tests/test_harness_shims.py -q`
- [ ] AC-2: pre-existing tests pass unmodified
  - verify: `make test && make eval`
