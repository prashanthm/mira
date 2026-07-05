# ADR-036: Prompt-Injection & Tool-Abuse Defense

## Status

Accepted

## Context

The MIRA-IDENTITY epic's own problem statement names "prompt-injection defense" alongside per-agent
identity and task-scoped tokens as what the epic delivers: "each agent touches only what its task
requires; agents are discoverable." [ADR-034 (Proposed)](./adr-034-per-agent-identity-and-task-scoped-tokens.md)
narrows *which entitlements* a specialist's token can exercise per dispatch, and
[ADR-035 (Proposed)](./adr-035-agent-cards-and-a2a-discovery.md) makes specialists discoverable. Neither
ADR bounds *which tools a specialist attempts to call* once dispatched, or protects a specialist from
indirect prompt injection carried in tool results and retrieved content. ADR-034 explicitly defers this:
it "[does] not cover ... prompt-injection defense (ADR-036, explicitly coupled to this ADR per the
MIRA-IDENTITY epic)."

[ADR-037 (Accepted)](./adr-037-bidirectional-guardrail-pipeline.md) already decides the **full**
bidirectional (input+output) guardrail pipeline — placement in the [ADR-009](./adr-009-middleware-pipeline-architecture.md)
guardrail-IN/-OUT stages, defense-in-depth with an optional secondary cloud layer, composition with
hallucination (ADR-038) and HITL (ADR-039) — but that is **Phase 3 / MIRA-SAFETY** scope. ADR-037
names this ADR as the owner of injection-*detector design* within its guardrail-IN stage, not the
pipeline shape itself. This ADR is narrower: it decides the **Phase-2, MIRA-IDENTITY-scoped slice** —
what runs at the specialist dispatch boundary, alongside per-agent identity, using what ADR-031
(Accepted, Typed Tool Contracts) already declares per tool, so two live specialists (research,
finance) do not ship Phase 2 with zero tool-reachability bound and zero injected-content handling.

This ADR does **not** re-decide the ADR-009 guardrail-IN/-OUT pipeline placement, the full
input/output content-safety pipeline, hallucination/topic-drift detection (ADR-038), or HITL
escalation mechanics (ADR-039) — all Phase 3 / ADR-037 scope. It decides how a specialist's callable
tool set is bounded at dispatch time and how tool results are marked untrusted before re-entering a
specialist's context.

## Decision Drivers

1. **MIRA-IDENTITY epic commitment** — "prompt-injection defense" is named explicitly in the epic's
   problem/build statement and acceptance criterion ("each agent touches only what its task
   requires"); this is not optional Phase-2 scope.
2. **ADR-034's explicit coupling** — ADR-034 defers prompt-injection defense to this ADR "explicitly
   coupled ... per the MIRA-IDENTITY epic," meaning the two decisions must compose, not duplicate.
3. **ADR-037's scope reservation** — ADR-037 (Accepted) names this ADR as the injection-detector-design
   owner within its guardrail-IN stage but reserves pipeline shape/placement for itself (Phase 3);
   this ADR must stay inside that boundary, not preempt it.
4. **ADR-031's existing tool-risk contract** — every tool already carries `readOnlyHint` /
   `destructiveHint` / `openWorldHint` annotations (Accepted); a Phase-2 control that consumes this
   directly needs no new schema or model.
5. **OWASP LLM01:2025 (Prompt Injection) / LLM06:2025 (Excessive Agency)** — indirect injection via
   tool results is the dominant agentic attack vector; unbounded tool-call capability is a
   independently-ranked risk that capability minimization (allowlisting) is the named mitigation for.
6. **Anthropic's own agentic-product containment practice** — a capability allowlist (safe/read-only
   tools bypass gating) plus a separate tool-output-inspection layer that marks tool-result content
   as untrusted before it re-enters the agent's context is the pattern Anthropic uses in its own
   production agent products.

## Research & Rubric

`Research & rubric — ADR-036`. Scored
deferring all injection/tool-abuse defense to Phase 3 vs a dispatch-time tool allowlist + tool-result
untrusted-content tagging (this ADR's candidate) vs pulling a full LLM-based injection classifier
forward into Phase 2, against: closing the MIRA-IDENTITY acceptance criterion, coverage of OWASP
LLM01/LLM06, reuse of the existing ADR-031 tool-risk contract, non-duplication with ADR-034's token
scoping, staying inside ADR-037's reserved scope boundary, and Phase-2 operational cost. The
allowlist + tagging option wins — it is the only option that closes the epic's acceptance criterion
without either shipping Phase 2 with no defense or preempting ADR-037's Phase-3 pipeline-shape
decision.

## Decision

Adopt a **dispatch-time tool allowlist derived from ADR-031's tool-risk annotations, plus tagging of
tool results as untrusted content**, as the Phase-2 MIRA-IDENTITY-scoped prompt-injection and
tool-abuse defense.

**1. Dispatch-time tool allowlist**
- When the supervisor ([ADR-014](./adr-014-domain-agent-supervisor-routing.md)) dispatches to a
  specialist, the specialist's **callable tool set for that dispatch** is constrained to an explicit
  allowlist derived from the task, not the specialist's full tool catalog.
- Tools annotated `readOnlyHint` ([ADR-031](./adr-031-typed-tool-contracts.md)) are auto-permitted for
  any task the specialist is dispatched for.
- Tools annotated `destructiveHint` or `openWorldHint` require the task-scoped token
  ([ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md)) audience/scope to explicitly cover
  that tool; if it does not, the call is rejected **before** it reaches MCP — the specialist cannot be
  injected into calling a tool outside its dispatched task's allowlist, regardless of what an injected
  instruction tells it to do.
- This is a second, independent layer from ADR-034's token-audience narrowing: the token bounds which
  MCP resource server will honor the call at all; the allowlist bounds which calls the specialist-graph
  will even attempt. Neither replaces the other.

**2. Tool-result untrusted-content tagging**
- Every tool result returned to a specialist is wrapped/tagged as untrusted content before it
  re-enters the specialist's reasoning context — matching how tool outputs are the dominant indirect
  prompt-injection vector (OWASP LLM01).
- Tagging does not attempt content classification or removal (no injection-detection model runs in
  this ADR's scope — that is reserved for ADR-037/038 if warranted); it structurally marks the
  boundary so the specialist's system-level framing treats tool-result content as data, not
  instructions, consistent with standard prompt-injection hardening practice.

**3. Failure mode**
- A tool call rejected by the allowlist (not covered by the dispatch's task scope) fails that tool
  call closed and is logged as a `tool_call_rejected_scope` event with `tenant_id`, `user_id`,
  `correlation_id`, specialist id, and the rejected tool name — never silently retried with broader
  scope. The specialist's orchestration step surfaces this per
  [ADR-014](./adr-014-domain-agent-supervisor-routing.md)'s failure-boundary policy (retry with a
  narrower approach, reroute, or escalate to HITL once [ADR-039](adr-list.md) exists) — it never
  falls back to an unscoped tool set.

**4. Scope of this ADR**
- Covers **dispatch-time tool-call reachability** and **tool-result untrusted-content tagging** for
  the MIRA-IDENTITY epic's specialist dispatch boundary. Does not cover: the ADR-009 guardrail-IN/-OUT
  pipeline shape or placement, output-side content safety, hallucination/topic-drift detection
  (ADR-038), HITL escalation mechanics (ADR-039), or any LLM-based injection-classification model —
  all reserved for [ADR-037 (Accepted)](./adr-037-bidirectional-guardrail-pipeline.md)'s Phase-3 scope.
- Does not solve **confused-deputy within an allowlisted tool's scope** (e.g. an allowlisted
  `ledger.query` call injected into using unintended arguments) — argument-level/semantic validation
  is out of scope here; flagged as an open risk for Phase-3 output-side and hallucination controls to
  address.
- Does not cover tool-*description*/metadata poisoning at registration time — flagged as an
  implementation-phase gap, a candidate for the MIRA-SKILLS governed-registry decision rather than a
  runtime dispatch-time control.

**Rejected alternatives:**

- **Defer all injection/tool-abuse defense to Phase 3 (ADR-037)** — Rejected: leaves the MIRA-IDENTITY
  epic's own acceptance criterion unmet and contradicts its explicit "prompt-injection defense"
  commitment; ships two live specialists (research, finance) with no tool-reachability bound beyond
  the Phase-1 shared identity ADR-034 is closing.
- **Pull a full LLM-based injection-classifier model forward into Phase 2** — Rejected: duplicates
  work ADR-037 (Accepted) already reserves for Phase 3 (pipeline shape, latency budget, false-positive
  tuning, cost-ceiling accounting under ADR-013), and is not required to satisfy the MIRA-IDENTITY
  acceptance criterion, which is about tool *reachability*, not content classification.

## Implemented Mechanism (Phase D)

ADR-037 named this ADR the owner of injection-detector design within its guardrail-IN stage. With
the Phase-D MIRA-SAFETY slice landed, that detector design is now implemented in
`src/mira/core/guardrails.py`, running in the ADR-009 `guardrail_in` stage on top of the Phase-2
dispatch-time allowlist and untrusted-content tagging decided above (which remain in force —
`specialist_scaffold.filter_tools_by_domain` and `fabric/provenance.py`'s untrusted default):

- **`InjectionDetector`** — a deterministic, case-insensitive, whitespace-tolerant pattern detector
  for instruction-override shapes: "ignore (all) previous/prior/above instructions", "disregard
  your/the (system) prompt", "you are now", "reveal your/the (system) prompt", "override (your)
  rules/instructions", "forget … instructions". Patterns target *imperative override* phrasing, so
  benign text that merely mentions "instructions" or "prompt" does not match (false-positive guard
  asserted by the `evals/test_injection_corpus.py` green set). `extra_patterns` is the config hook
  for tenant/domain-specific additions. `check(text)` returns a frozen `ViolationFinding`
  (stable code, matched pattern, evidence snippet) for audit.
- **`ToolAbuseDetector`** — validates every proposed tool call against the ADR-031 contract
  registry, fail closed: unknown tool name → violation; arguments failing the contract's
  `inputSchema` (jsonschema) → violation — closing the confused-deputy/argument-level gap this ADR
  flagged as open for Phase 3; `destructiveHint` tools require an explicit per-call allow flag.
- **`GuardrailInMiddleware`** — the `guardrail_in` stage: runs the pluggable detector list over
  `ctx.attributes["query"]` and the optional `ctx.attributes["tool_calls"]`, records findings in
  `ctx.attributes["guardrail_in_findings"]`, and raises `GuardrailViolation` on any finding — the
  handler never runs. Fail-closed defaults: the injection detector is on unless explicitly
  replaced, and tool calls presented without a configured contract registry are rejected.
- **Corpus gate** — `evals/test_injection_corpus.py` (ADR-045) asserts a red corpus of injection,
  prompt-reveal, role-hijack, tool-smuggling, and destructive-tool attempts is blocked, and a green
  corpus of benign near-misses is not.

Matched injection findings feed the ADR-039 risk policy (a finding classifies the action as
high-risk → HITL hold) and land in the ADR-040 decision trace. An LLM-based classifier remains a
deferred secondary layer behind the same detector seam (ADR-037's defense-in-depth slot).

## Consequences

### Becomes Easier

- The MIRA-IDENTITY epic's acceptance criterion ("each agent touches only what its task requires") is
  provably closed at the dispatch layer, not just the token layer — an injected instruction cannot
  make a specialist call a tool outside its dispatched task's allowlist.
- Zero new schema or model: the allowlist consumes ADR-031's existing `readOnlyHint` /
  `destructiveHint` / `openWorldHint` annotations directly.
- Defense-in-depth with ADR-034 at no extra cost: token-audience scoping and tool-allowlist scoping
  are independent layers that fail closed together, not a single point of failure.
- Tool-result tagging gives ADR-037's future Phase-3 pipeline a clean boundary to build on — the
  untrusted-content convention this ADR establishes does not need to be reinvented when the full
  guardrail pipeline lands.

### Becomes Harder

- Confused-deputy attacks within an allowlisted tool's scope (wrong arguments to a permitted tool) are
  not addressed here — a real gap until ADR-037's output-side/hallucination controls land in Phase 3.
- Tool-description/metadata poisoning at registration time is not addressed here — a specialist that
  discovers a compromised tool via ADR-035's discovery mechanism is not protected by this ADR's
  runtime controls alone; requires a registration-time control this ADR does not decide.
- Two independent scoping layers (ADR-034 token audience, this ADR's allowlist) must be kept
  consistent as new tools/specialists are added — a maintenance surface that did not exist under the
  Phase-1 shared identity.

## Applies To

- **MIRA-IDENTITY** — this ADR's primary epic; closes the epic's
  prompt-injection-defense and tool-reachability acceptance criterion alongside ADR-034/035.
- **MIRA-AGENTS** — every domain specialist (research, finance) is
  dispatched under this ADR's tool allowlist and tags its tool results as untrusted content.
- [ADR-014](./adr-014-domain-agent-supervisor-routing.md) — the supervisor→specialist dispatch this
  ADR's allowlist gates; failure mode follows its failure-boundary policy.
- [ADR-031](./adr-031-typed-tool-contracts.md) — the tool-risk annotation contract this ADR's allowlist
  consumes directly.
- [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md) — composes as an independent scoping
  layer (token audience vs tool-graph reachability); explicitly coupled per the MIRA-IDENTITY epic.
- [ADR-037](./adr-037-bidirectional-guardrail-pipeline.md) — this ADR is the Phase-2 slice; ADR-037
  (Accepted) names it as the injection-detector-design owner within its Phase-3 guardrail-IN stage and
  reserves pipeline shape/placement, hallucination (ADR-038), and HITL escalation (ADR-039) for itself.

## Links

- ADR file: `docs/adr/adr-036-prompt-injection-and-tool-abuse-defense.md`
- Research & rubric: `research/adr-036-prompt-injection-and-tool-abuse-defense.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-036
- Epic: MIRA-IDENTITY
