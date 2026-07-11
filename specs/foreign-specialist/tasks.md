# Foreign Specialist Adapter — Tasks

> **Feature slug:** foreign-specialist · Spec: [`spec.md`](./spec.md) · Plan: [`plan.md`](./plan.md)

Ordered implementation units.

---

## Task 1 — Stub foreign agent + wrapper

`StubEchoAgent`, `RoutableAgent` widening, `ForeignSpecialist` + card/registration helpers.

## Loop AC

- [ ] AC-1: stub imports contracts only; deterministic grounded answers; zero-step budget ⇒ `bound_exceeded`
  - verify: `pytest tests/test_stub_agent.py -q`
- [ ] AC-2: injection blocked pre-call; invalid trace ⇒ structured error; ledger attribution by domain
  - verify: `pytest tests/test_foreign_specialist.py -q`

---

## Task 2 — Foreign evals

Goldens + shared eval registry + foreign-specific eval assertions.

## Loop AC

- [ ] AC-1: foreign goldens route via supervisor and score 1.0; `eval_gate()` covers them
  - verify: `make eval`

---

## Task 3 — CLI adapter (optional/flagged)

Subprocess envelope→trace adapter + `FOREIGN_AGENT_CMD` wiring.

## Loop AC

- [ ] AC-1: subprocess-of-self round-trip; timeout/bad-JSON ⇒ `status="error"`; absent flag ⇒ no change
  - verify: `pytest tests/test_cli_adapter.py -q`
