# ADR-029: Agentic RAG Strategy

## Status

Accepted

## Context

A single-shot retrieve-then-generate pass is brittle: when the
[ADR-028](./adr-028-hybrid-retrieval.md) pipeline returns weak or off-topic evidence, a plain RAG
flow generates anyway and the failure surfaces as a confident wrong answer. Mira's reasoning loop
([ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) ReAct) already gives agents the
machinery to observe, reflect, and act again — with layered safety bounds (`ReasoningBudget`:
steps, tokens, time, cost) so no loop runs unbounded. The open question was how retrieval
participates in that loop as a first-class, self-correcting step rather than a one-time preamble.

The boundary rules constrain the answer's shape: the ADR-013 loop lives in `orchestration/`
(LangGraph is quarantined there per [ADR-007](./adr-007-core-agent-stack-and-framework.md)), while
retrieval is business-layer code that must stay framework-free
([ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md)). Every extra
retrieval round is potential extra model spend, coupling this decision to cost-aware routing
([ADR-011](./adr-011-model-fallback-cost-routing.md)) and cost attribution
([ADR-042](./adr-042-agentops-telemetry-and-llm-cost-attribution.md)); whether the added loops
earn their cost is measured by the eval gate
([ADR-045](./adr-045-eval-framework-ci-safety-gate.md)).

## Decision Drivers

1. **Weak evidence must be caught before generation** — a failed retrieval should trigger
   correction or honest degradation, not a confident wrong answer.
2. **ADR-013's budget discipline** — any retry loop must be bounded the same way the reasoning
   loop is; an unbounded retrieval loop is the same failure class ADR-013 closed.
3. **Layer boundaries (ADR-001/ADR-007)** — retrieval cannot import `orchestration/`, so the
   loop must be a plain class that *mirrors* the budget pattern rather than reusing the LangGraph
   machinery.
4. **Offline determinism (ADR-045)** — grading and rewriting need deterministic reference
   implementations so the corrective behavior itself is eval-gated without model calls.
5. **Hook-shaped extension points** — live-model critique and rewriting are known follow-ons;
   they must slot in without changing the loop contract.

## Research & Rubric

Scored a Corrective-RAG style retrieve→grade→re-query loop with pluggable grader/rewriter against
single-shot RAG, generation-side self-critique only (grade the answer, not the evidence), and a
full Self-RAG implementation (model-emitted reflection tokens) on grounding improvement,
offline testability, budget safety, and layer fit. The corrective loop wins: it intervenes at the
cheapest point (before generation), needs no model to be testable, and its grader/rewriter hooks
subsume the model-backed variants later without a contract change.

## Decision

Adopt a **bounded corrective retrieval loop — retrieve → grade → re-query — as a plain
business-layer class with pluggable grading and rewriting**: `CorrectiveRetriever` in
`retrieval/agentic.py`, returning a structured `RetrievalOutcome`.

**1. Loop shape.**
Each attempt runs the ADR-028 hybrid retriever, then a
`grader: Callable[[query, hits], bool]` judges the evidence. A passing grade returns immediately;
a failing grade rewrites the query via `rewriter: Callable[[query, attempt], str]` and retries.
The loop is bounded by `max_attempts` (default 3) — a hard cap regardless of grading behavior.

**2. Budget discipline without an orchestration import.**
The loop also accepts an optional **duck-typed step budget** exposing the ADR-013
`ReasoningBudget` surface (`check_before_step()` / `record_step()`). The budget is consulted
before and charged after every retrieval attempt; exhaustion returns immediately with
`budget_exhausted=True` and the best hits gathered so far. The real `ReasoningBudget` object
plugs in directly (verified by test), yet `retrieval/` never imports `orchestration/` — the
pattern is mirrored, not the dependency.

**3. Deterministic reference grader and rewriter.**
The default grader accepts non-empty hits whose top fused score clears a threshold
(`min_top_score`). The default rewriter performs deterministic query relaxation against the
sparse index's vocabulary: drop out-of-vocabulary tokens first (over-specific terms are what
poison retrieval), else drop the single lowest-idf (most common) token, else append an attempt
marker so no identical query is ever re-run. Both are plain callables — the hooks, not the
defaults, are the contract.

**4. Structured outcome, honest failure.**
`RetrievalOutcome` carries the final hits, `attempts`, `corrected` (True only when a rewrite
happened *and* the final grade passed), `budget_exhausted`, and the query sequence. An exhausted
loop returns its best evidence uncorrected rather than raising — the caller decides whether to
degrade, escalate ([ADR-039](./adr-039-hitl-escalation.md)), or surface uncertainty
([ADR-041](./adr-041-explanation-api-and-uncertainty.md)).

**5. Eval coverage.**
`evals/test_retrieval_evals.py` includes a corrective-RAG golden: a deliberately over-specific
query fails a deterministic relevance grade on attempt 1 and passes after the default
out-of-vocabulary relaxation — the correction loop itself is regression-gated (ADR-045).

**Rejected alternatives:**

- **Single-shot RAG (status quo)** — Rejected: weak evidence flows straight into generation; the
  exact confident-wrong-answer failure this ADR exists to close.
- **Grade the generated answer instead of the evidence** — Rejected as the primary mechanism:
  strictly more expensive (generation happens before the check) and harder to attribute; answer-
  side hallucination controls remain [ADR-038](./adr-038-hallucination-and-topic-drift-controls.md)'s
  layer, not a substitute for evidence grading.
- **Build the loop inside the ADR-013 LangGraph graph** — Rejected: welds retrieval to the
  orchestration framework, violating the ADR-001/ADR-007 containment that keeps business logic
  framework-free and offline-testable. The reasoning loop *calls* the corrective retriever as a
  tool; it does not absorb it.

## Consequences

### Becomes Easier

- Over-specific and low-quality queries self-correct deterministically — demonstrated end-to-end
  in the eval gate without any model call.
- The retrieval loop and the reasoning loop share one budget object per request, so total agentic
  spend stays under the ADR-013 ceilings and attributable per ADR-042.
- Live-model grading/rewriting lands as a drop-in callable pair — no loop, outcome, or caller
  changes.
- Declining to answer is a first-class outcome (`corrected=False` with telemetry), feeding
  ADR-041 uncertainty surfacing.

### Becomes Harder

- Every retrieval consumer must handle a `RetrievalOutcome` (attempts/corrected/budget state),
  not a bare hit list.
- The default grader is a floor, not a relevance model: a wrong-but-high-scoring top hit passes
  it; real relevance grading waits on the model-backed hook.
- Worst-case retrieval latency multiplies by `max_attempts`; budget tuning per profile becomes a
  real operational knob.

## Deferred

- **Live-model grading** — an LLM relevance/sufficiency critic behind the same `grader` hook,
  with its calls charged to the shared budget (ADR-011/ADR-042).
- **Live-model query rewriting** — model-generated reformulation behind the same `rewriter` hook.
- **KB switching and graph-neighborhood widening** — re-query strategies that change *where* to
  look, not just the query text; the graph half arrives with
  [ADR-030](./adr-030-graph-vector-fusion.md) fusion.
- **Surfacing grade verdicts as user-visible uncertainty** — the ADR-041 explanation surface
  consuming `RetrievalOutcome` telemetry.

## Applies To

- `src/mira/retrieval/agentic.py` — this decision's home.
- [ADR-028](./adr-028-hybrid-retrieval.md) — the retrieval primitive the loop invokes.
- [ADR-013](./adr-013-reasoning-pattern-and-loop-safety.md) — the budget pattern the loop mirrors
  (duck-typed `ReasoningBudget` surface).
- [ADR-011](./adr-011-model-fallback-cost-routing.md) /
  [ADR-042](./adr-042-agentops-telemetry-and-llm-cost-attribution.md) — cost governance of the
  deferred model-backed hooks.
- [ADR-041](./adr-041-explanation-api-and-uncertainty.md) — uncertainty surface consuming
  outcome telemetry.
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — corrective-RAG golden gating the loop.

## Links

- ADR file: `docs/adr/adr-029-agentic-rag.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-029
