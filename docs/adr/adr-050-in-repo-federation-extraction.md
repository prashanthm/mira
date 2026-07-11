# ADR-050: In-Repo Federation Extraction (Contracts & Harness Packages)

## Status

Accepted

## Context

Evaluating Mira against the "meta-harness" pattern (a control layer that runs, compares, and
improves arbitrary agents) concluded that Mira is the *managed agent*, not the control layer —
but that its governance and improvement internals are exactly the components such a layer needs:
guardrail detectors (ADR-036/037/038), cost attribution (ADR-042), trace scoring and the
regression gate (ADR-045), and eval-gated versioning with kill switch (ADR-012). Today those
live inside `mira.*` and are therefore unusable by any other agent.

The chosen strategy is **federation, not accretion**: make the planes adoptable by *any* agent
via the public contracts (ADR-049), keep Mira as the reference agent that dogfoods them, and
grow by contract adoption rather than by absorbing other agents into Mira's process.

## Decision Drivers

1. **A later repo split must be mechanical** — a directory move plus packaging, no import
   rewrites inside the extracted code.
2. **Zero breakage** — every existing import path and test keeps working.
3. **Mechanical enforcement** — dependency direction must be a lint rule (ADR-001 precedent),
   not a convention.
4. **Small reviewable steps** — each extraction lands independently and is independently
   revertible.

## Decision

Two new **top-level** src packages beside `mira`, with a strictly one-way, lint-enforced
dependency direction:

```
mira  ──may import──▶  mira_harness  ──may import──▶  mira_contracts
(nothing in mira_contracts or mira_harness may import mira.*)
```

- **`src/mira_contracts/`** — schemas + validation only (ADR-049), plus the public half of the
  typed tool contract (`tooling.py`, moved from `mira.tools.contract` — it already depends only
  on `jsonschema`).
- **`src/mira_harness/`** — the governance & improvement planes over those contracts:
  `policy.py` (guardrail *detectors* moved from `mira.core.guardrails`; the middleware halves
  stay in `mira.core` — they are Mira's transport), `cost.py` (cost attribution, with
  `AttributedSpan.from_span` duck-typed to sever the `mira.model.routing` import), `scoring.py`
  (from `evals/trace_scoring.py`), `gate.py` (the generic gate core:
  `run_gate(cases, runner)` over an `EnvelopeRunner`), `versioning.py` (moved verbatim — it has
  zero `mira` imports already), and the ADR-051 adapters (`stub_agent.py`, `cli_adapter.py`).

**Why not `src/mira/harness/`:** anything under `mira/` shares the package namespace, so a later
split would rewrite every internal import at split time. Top-level packages with a no-`mira`
lint rule make the split a `git mv`.

**Shim policy.** Every moved module leaves a re-export shim at its old path with an explicit
`__all__` and a docstring naming the new home. Existing test files keep importing the old paths —
that *is* the compatibility regression proof — plus one identity test per shim
(`old.X is new.X`). Shims are never forked: new symbols land in the new module only.

**Enforcement.** `tools/lint_imports.py` gains layer detection for the two new packages and two
rules: (a) neither package may import `mira`/`mira.*`; (b) `mira_contracts` may not import
`mira_harness`. The `Makefile` `lint-imports` target scans all three src roots. Both new
packages classify as "business" under the existing path rules, so the langgraph/cloud-SDK bans
apply to them automatically. A fixture guards the path-substring trap (a directory named
`orchestration` inside `mira_harness` must **not** gain langgraph rights).

**Explicitly deferred** (extraction buys nothing yet): `core/identity.py` (token exchange stays
agent-side until tokens cross a process boundary), `core/escalation.py`,
`core/decision_trace.py`, `fabric/provenance.py` — they *consume* the contracts via the
byte-compatible trace shape and need not move. Separate distribution/PyPI packaging is out of
scope; both packages ship inside the single `mira` distribution for now.

## Consequences

- The governance planes become adoptable with `pip install`-level ease once split, and are
  provably Mira-free today (lint + the ADR-051 stub agent's no-`mira`-import test).
- Two package roots mean contributors must know where new governance code lands: contracts and
  planes go in the new packages; Mira-specific wiring stays in `mira.*`. AGENTS.md records the
  rule.
- Re-export shims add one indirection layer at the old paths; the identity tests keep them
  honest.

## Applies To

`src/mira_contracts/`, `src/mira_harness/`, `tools/lint_imports.py`, `Makefile`,
`pyproject.toml`, every shimmed module listed above.

## Links

- [ADR-049](./adr-049-public-execution-envelope-and-trace-contracts.md) — the contracts
- [ADR-051](./adr-051-foreign-agent-adapter-experiment.md) — first consumer of the extraction
- [ADR-001](adr-list.md), [ADR-007](adr-list.md), [ADR-012](adr-list.md),
  [ADR-042](adr-list.md), [ADR-045](adr-list.md)
