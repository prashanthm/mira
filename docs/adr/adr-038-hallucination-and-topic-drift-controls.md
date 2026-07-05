# ADR-038: Hallucination & Topic-Drift Controls

Status: Proposed

## Context

Grounding via retrieval (ADR-028/029/030) is necessary but not sufficient: a model can be handed
correct evidence and still assert claims the evidence does not support, and an agent scoped to a
domain can drift into answering questions it has no corpus, tools, or mandate for. Mira treats
both as output-safety failures that must be detected and acted on at the platform layer, not left
to prompt discipline in each specialist.

The open question is which detection and control mechanisms to adopt. For hallucination:
candidates include claim-level faithfulness checks against retrieved evidence (NLI/grader-model
scoring of claim→source support), self-consistency sampling, and hard requirements that factual
claims carry ADR-040 decision-trace citations before an answer is released. For topic drift:
domain-scope classification of both the incoming request and the outgoing answer against the
specialist's declared scope (its ADR-035 agent card is the natural scope declaration), with
off-scope requests refused or re-routed by the supervisor rather than half-answered. Open
sub-questions include detection cost/latency budgets, thresholds and what happens on breach
(block, rewrite, caveat, or escalate to a human via ADR-039), and how verdicts are logged for
eval and audit.

Whatever is selected must be measurable: the ADR-045 adversarial suite already probes for
unsupported claims and scope violations, so this ADR's controls become the runtime counterpart of
those CI assertions.

## Decision (pending)

This ADR will select the hallucination-detection and topic-drift/domain-scope controls and their
enforcement actions. It builds on the guardrail_in / guardrail_out middleware stages (ADR-009,
composed by the ADR-037 bidirectional guardrail pipeline) as the enforcement points — input-side
scope checks in guardrail_in, claim-faithfulness and drift checks in guardrail_out — and on
`orchestration/interrupts.py` for the cases where a failed check should pause the run for human
review (ADR-039) instead of hard-failing.

Planned phase: D (safety & trust, with ADR-036, ADR-039, ADR-040, ADR-041).
