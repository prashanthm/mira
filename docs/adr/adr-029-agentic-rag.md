# ADR-029: Agentic RAG Strategy

Status: Proposed

## Context

A single-shot retrieve-then-generate pass is brittle: when the ADR-028 pipeline returns weak or
off-topic evidence, a plain RAG flow generates anyway and the failure surfaces as a confident
wrong answer. Mira's reasoning loop (ADR-013 ReAct) already gives agents the machinery to
observe, reflect, and act again — the open question is how retrieval participates in that loop as
a first-class, self-correcting step rather than a one-time preamble.

The current direction is Self-RAG / Corrective-RAG style loops: the agent critiques retrieved
evidence (relevance, sufficiency, support), and on a failed critique it re-queries — rewriting the
query, switching knowledge bases, widening to the ADR-030 graph neighborhood, or declining to
answer. Open sub-questions include where the critique runs (a grader model call vs. lightweight
scoring), how many refinement rounds are allowed before the loop-safety bounds of ADR-013 cut it
off, whether critique verdicts are surfaced to the user as uncertainty (feeding ADR-041), and how
much latency/cost budget agentic retrieval may consume per request given ADR-011's cost-aware
routing.

Because every extra retrieval round is an extra model call, this decision is coupled to cost
attribution (ADR-042) and to the eval gate: ADR-045's golden and adversarial suites are the
measure of whether the added loops actually improve grounding enough to justify their cost.

## Decision (pending)

This ADR will select the agentic retrieval strategy — the critique/refine loop shape, its
termination and budget rules, and its integration into the ADR-013 reasoning loop. It builds on
the planned `retrieval/` package (the ADR-028 hybrid pipeline is the retrieval primitive the loop
invokes) and on the docs-connector corpus as the evaluation substrate, with grounding regressions
gated by ADR-045.

Planned phase: C (retrieval, with ADR-028 and ADR-030).
