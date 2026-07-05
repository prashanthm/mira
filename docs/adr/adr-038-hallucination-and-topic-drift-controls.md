# ADR-038: Hallucination & Topic-Drift Controls

## Status

Accepted

## Context

Grounding via retrieval (ADR-028/029/030) is necessary but not sufficient: a model can be handed
correct evidence and still assert claims the evidence does not support, and an agent scoped to a
domain can drift into answering questions it has no corpus, tools, or mandate for. Mira treats both
as output-safety failures that must be detected and acted on at the platform layer — not left to
prompt discipline in each specialist.

[ADR-037 (Accepted)](./adr-037-bidirectional-guardrail-pipeline.md) fixes *where* these controls
run: the guardrail-OUT stage of the [ADR-009](./adr-009-middleware-pipeline-architecture.md)
middleware chain, wrapping every exit — success, error, and per-chunk streaming. The
[ADR-045](./adr-045-eval-framework-ci-safety-gate.md) eval suite already asserts claim→source
linkage structurally (`evals/trace_scoring.py`'s grounding rule); this ADR selects the *runtime*
counterpart of those CI assertions. The candidates ranged from model-graded faithfulness checks
(NLI/grader scoring of claim→source support, self-consistency sampling) to purely structural
checks (every claim must carry provenance attribution before release).

## Decision Drivers

1. **Portability and determinism** — the primary control must run on every deployment profile,
   offline, with no model call ([ADR-047](./adr-047-deployment-profiles-and-packaging.md); ADR-037's
   "no safety property may depend solely on the secondary layer").
2. **Runtime/CI parity** — the runtime check must enforce the same rule the ADR-045 gate scores,
   so a result cannot pass CI and fail production semantics (or vice versa).
3. **Stream discipline** — per ADR-009/006, output checks must observe every streamed chunk but
   must never corrupt a stream mid-flight; only a final result may be blocked.
4. **Existing provenance spine** — connectors already attach `provenance{source_type, source_id}`
   to every record (ADR-020, `fabric/provenance.py`); a structural check consumes this directly
   with no new schema.
5. **Domain scoping already declared** — every specialist declares its tool prefixes
   (`DomainSpec.tool_prefixes`, ADR-014); topic drift is measurable against that declaration as
   plain data.

## Decision

Adopt **structural groundedness and topic-drift checks in the guardrail-OUT stage**, implemented in
`src/mira/core/guardrails.py`:

- **`GroundednessChecker`** — a structural claim→source check over the `SpecialistResult.to_dict`
  shape: a non-error result's answer must carry provenance attribution under the same recursive
  rule the ADR-045 trace scorer applies (a `provenance` mapping with `source_type` + `source_id`
  at the top level or on any nested mapping). Error results assert no claims and pass; an
  unattributed answer is an `ungrounded_answer` finding.
- **`TopicDriftDetector`** — a per-domain drift check constructed from plain
  `domain_id → tool_prefixes` data (no orchestration import from core): a result whose answer
  provenance `source_type` maps to a *different* domain's tool prefix than the routed domain is a
  `topic_drift` finding. Input-side scope enforcement remains the supervisor's routing plus the
  per-domain tool allow-list (ADR-014/036); this detector catches the output-side leak.
- **Enforcement (`CheckedGuardrailOutMiddleware`)** — extends the ADR-009 `GuardrailOutMiddleware`
  so every exit still flows through the parent's no-bypass discipline. Checker findings are
  appended to `ctx.attributes["guardrail_out_findings"]` for telemetry and the ADR-040 decision
  trace. A **groundedness violation on a final (non-stream-chunk) result raises
  `GuardrailViolation`** and blocks the response; **streamed chunks are recorded, never raised** —
  a stream is never broken mid-flight. Drift findings are recorded (audit + ADR-039 escalation
  input) rather than hard-blocked, since a grounded but drifted answer is salvageable by human
  judgment.
- **Wiring** — `build_guarded_pipeline(contracts=…, domain_prefixes=…)` returns an ADR-009
  pipeline with both guardrail stages configured; groundedness is always on (fail closed), drift
  activates when domain prefixes are supplied.

**Rejected alternatives:**

- **Model-graded faithfulness (NLI/grader) as the primary control** — Rejected as primary: needs a
  model call on every response (latency + ADR-013 cost-ceiling pressure) and is unavailable
  offline/on-prem. It remains the intended *secondary* layer behind the same checker seam
  (see Deferred).
- **Prompt-discipline only (no runtime check)** — Rejected: unverifiable, per-specialist, and
  contradicts the MIRA-SAFETY commitment that unsafe output is blocked at the platform boundary.
- **Blocking on topic drift** — Rejected for now: a grounded answer from the wrong corpus is a
  routing defect to surface and escalate, not to hard-fail; hard-blocking would convert supervisor
  misroutes into user-facing errors.

## Consequences

### Becomes Easier

- Ungrounded answers cannot leave the platform: the same rule CI scores is enforced at runtime,
  fail closed, on every profile with zero model cost.
- Drift is observable: findings land in `guardrail_out_findings`, the ADR-040 trace, and the
  ADR-039 risk policy without breaking responses.
- The checker seam (`check(result_dict) -> ViolationFinding | None`) lets stronger detectors slot
  in without touching the pipeline.

### Becomes Harder

- Structural grounding proves *attribution*, not *faithfulness*: a claim can cite a real source it
  misrepresents. The check is honest about this — ADR-041's uncertainty bands are labeled
  structural, and semantic verification is explicitly deferred.
- Results must keep the `SpecialistResult` dict shape (answer + provenance) for the checkers to
  apply; free-form payloads pass unchecked.

### Deferred

- **Model-graded groundedness** (NLI/grader claim→source scoring, self-consistency sampling) as a
  secondary layer behind the same `GroundednessChecker` seam, costed inside the ADR-013 ceiling.
- **Semantic drift scoring** (embedding/classifier similarity between query, answer, and the
  routed domain's declared scope) behind the same `TopicDriftDetector` seam.
- Per-tenant thresholds and block-vs-caveat policy for drift findings.

## Applies To

- **MIRA-SAFETY** — output-side hallucination/drift controls (with ADR-037).
- [ADR-009](./adr-009-middleware-pipeline-architecture.md) — the guardrail-OUT stage these checks run in.
- [ADR-037](./adr-037-bidirectional-guardrail-pipeline.md) — the pipeline that composes this boundary.
- [ADR-039](./adr-039-hitl-escalation.md) — findings feed the risk policy; salvageable failures escalate.
- [ADR-040](./adr-040-decision-trace-audit.md) — findings land in the decision-trace record.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — the CI gate whose grounding rule this enforces at runtime.

## Links

- ADR file: `docs/adr/adr-038-hallucination-and-topic-drift-controls.md`
- Implementation: `src/mira/core/guardrails.py`; tests: `tests/test_guardrails.py`
- Catalog: [adr-list.md](adr-list.md) — ADR-038
