# ADR-045: Eval Framework & CI Safety Gate

## Status

Accepted

## Context

The product brief commits MIRA-EVAL to "golden + adversarial tests, CI gates" so "regressions caught
before merge; bad prompts/tools roll back." The predecessor PoC evaluation found **no eval infrastructure**
at all — a production-readiness gap. This ADR decides two things the title implies: **whether the
gate blocks**, and **what eval tooling runs it** — given the agent framework is LangGraph
([ADR-007](./adr-007-core-agent-stack-and-framework.md)) and the containment rule requires eval to be
**framework-agnostic** so it survives a framework change.

(This supersedes an earlier draft that was re-sequenced behind the framework decision and cited
now-removed OpenSpec material; the design here is re-grounded on industry standards.)

## Decision Drivers

1. **Governance (EU AI Act / NIST AI RMF / ISO 42001)** — high-risk AI must be tested pre-deployment
   and monitored after — a gate, not a one-off.
2. **Adversarial coverage (OWASP LLM Top 10 / MITRE ATLAS)** — golden-path tests are insufficient;
   injection/jailbreak/evasion cases are required.
3. **ADR-007 containment** — eval must not couple to LangGraph/LangChain; score emitted traces, not
   framework internals.
4. **Portability** — the suite must run in CI on every profile incl. on-prem (no cloud eval service dependency).
5. **MIRA-EVAL** — golden + adversarial datasets, blocking CI gate, "regressions caught before merge."

## Research & Rubric

`Research & rubric — ADR-045`. Scored two decisions: **(A)** gate policy (no gate / advisory / blocking) and **(B)** tooling (custom pytest / DeepEval / promptfoo·Inspect / LangSmith). A blocking golden+adversarial gate wins on the governance + adversarial-coverage drivers; a **pytest-orchestrated, trace/OTLP-based suite using a pytest-native OSS library (DeepEval), framework-agnostic — not LangSmith** — wins on containment + CI-native pass/fail + portability. Self-contained on NIST AI RMF, EU AI Act, ISO 42001, OWASP LLM Top 10, MITRE ATLAS, OpenTelemetry, and the eval-tool docs; internal docs corroborate.

## Decision

**(A) Adopt a blocking golden + adversarial eval suite as a CI safety gate.**

```
evals/
  datasets/   golden (source-platform-backed + platform-free tasks, domain-stratified) + adversarial (injection, jailbreak, drift)
  functional/ task completion, tool-selection correctness
  safety/     refusal, guardrail-bypass, entitlement-bypass
  domain/     domain grounding: entity resolution, unit normalization, provenance
```

- Runs in CI on every change to prompts, tools, agent code, or eval datasets.
- A **safety or regression** failure **blocks** merge/deploy; functional regressions block per a
  severity threshold set in the MIRA-EVAL spec. Staged with prompt/tool versioning + kill switch
  ([ADR-012](adr-list.md)).

**(B) Tooling: a pytest-orchestrated, trace/OTLP-based suite using a pytest-native OSS eval library.**

- **pytest** orchestrates (markers `@pytest.mark.safety` / `domain`, CI-native pass/fail).
- Evals **score emitted OpenTelemetry traces** (inherited MCP-server ADR-013, [ADR-042](adr-list.md)), not LangGraph internals — so the suite is **framework-agnostic** ([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment) and survives a framework change.
- Metrics via a **pytest-native OSS library (DeepEval)**; promptfoo / Inspect AI are acceptable
  model-agnostic alternatives. Models are reached through the gateway ([ADR-010](adr-list.md)), not vendor SDKs.
- **Not LangSmith** — its LangChain coupling reintroduces the vendor lock-in the containment rule forbids.
- Domain evals assert every factual claim traces to a source record (decision traces, [ADR-040](adr-list.md));
  provenance and unit normalization preserved. Each run publishes an eval blind-spots report.

**Rejected alternatives:**

- **No gate / advisory evals** — Rejected: fails the pre-deploy-testing obligation (EU AI Act/NIST);
  an ignorable safety signal lets a known-failing adversarial case ship.
- **Golden-only (no adversarial)** — Rejected: insufficient per OWASP/ATLAS; misses the injection/drift
  failures that matter most in a regulated setting.
- **LangSmith / framework-coupled eval** — Rejected: violates ADR-007 containment; cloud/service pull
  breaks on-prem portability.
- **Pure custom harness** — Rejected as unnecessary: a pytest-native OSS library covers the metrics
  with less maintenance; custom code is reserved for trace-scoring glue and domain checks.

## Consequences

### Becomes Easier

- Prompt/tool changes get an objective, blocking regression + safety signal before they ship.
- Eval is framework-agnostic (trace-based) — a framework change does not invalidate the suite.
- Safety posture is measurable (adversarial pass-rate, grounding/attribution coverage).
- Runs in CI on every profile incl. on-prem; closes the PoC's eval gap.

### Becomes Harder

- A blocking adversarial suite adds CI time/cost; the blocking threshold must be tuned to avoid flakiness.
- Golden/adversarial datasets need ongoing curation; an unmaintained dataset silently loses coverage.
- Claim→source assertions depend on ADR-040 (decision-trace store), not yet written — interface-only until it lands.
- OSS eval tools evolve fast; versions must be pinned (the trace-based core insulates against swaps).

## Applies To

- **MIRA-EVAL** — eval & release mgmt (primary)
- **MIRA-SAFETY** — eval measures guardrail effectiveness ([ADR-037](adr-list.md))
- **MIRA-XAI** — claim→source linkage ([ADR-040](adr-list.md))
- **MIRA-OBS** — eval outcomes feed AgentOps ([ADR-042](adr-list.md))
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — framework-agnostic eval per containment
- [ADR-012](adr-list.md) — staged rollout / kill switch; [ADR-040](adr-list.md) — decision traces asserted
- Inherited: MCP-server ADR-013 (metrics and tracing) — OTLP traces evals score

## Links

- ADR file: `docs/adr/adr-045-eval-framework-ci-safety-gate.md`
- Research & rubric: `research/adr-045-eval-framework-ci-safety-gate.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-045
