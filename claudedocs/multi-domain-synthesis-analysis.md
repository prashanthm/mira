# Multi-Domain Synthesis: Systems Analysis

*2026-07-11 · Mira orchestration architecture · prompted by: "should there be a
synthesizer per domain, or does one dynamically become a domain synthesizer?"*

---

## 1. The question, made precise

"Multi-domain" hides three independent design decisions that are usually
conflated:

| # | Decision | Candidate answers |
|---|----------|-------------------|
| D1 | **Who owns synthesis?** | (a) one synthesizer per domain family · (b) one shared synthesizer · (c) hierarchy: per-domain condensers + one global synthesizer |
| D2 | **What specializes the synthesizer?** | (a) nothing — fully generic · (b) the user's question · (c) the composition of results actually returned |
| D3 | **Who selects the participating domains?** | (a) a static list in code · (b) declarative registry metadata (cards) · (c) an LLM planner |

These must be analyzed separately because they change independently: you can
swap the selection mechanism (D3) without touching synthesis ownership (D1).

## 2. System decomposition: where change lands in Mira

The pipeline has five layers. For each, the question that matters for
multi-domain readiness is: **when a new domain family arrives, does this layer
change by *registration* (data) or by *modification* (code)?** This is the
open-closed principle applied at architecture scale — the same property that
plugin systems (VS Code extensions, pytest plugins, OSGi) are built around:
the core is closed, contribution points are open.

| Layer | Mechanism today | New family lands as |
|---|---|---|
| Tools | MCP discovery (`MCP_SERVERS`) | **registration** ✓ |
| Agents | `DomainSpec` + card + inference; foreign agents via ADR-051 envelope | code for native, **registration** for foreign |
| Fan-out set | `DEFAULT_ANALYZE_DOMAINS` tuple in `analyze.py` | **modification** ✗ |
| Subject identity | `symbol` + ticker regex in `analyze.py`/`service.py` | **modification** ✗ |
| Synthesis | generic contract + card-carried `synthesis_hint` (this week's change) | **registration** ✓ |

**Variation-axis analysis** (things that change together should live together):

- A *domain's* knowledge — its tools, its subject parsing, its synthesis
  caveats — already lives in one place (the facet triple + card). Correct.
- A *family's* knowledge — which domains analyze which kind of subject — lives
  in pipeline code. Incorrect: it changes exactly when a family is added, i.e.
  along the axis the user named ("a new domain tomorrow").

The two ✗ rows are therefore the genuine architectural debt. The synthesizer
prompt (the original complaint) was a symptom; the fan-out set and subject
identity are the disease.

## 3. Prior art

Four bodies of prior art bear directly on D1–D3.

### 3.1 Blackboard architectures (Hearsay-II, HASP — 1970s onward)

The classical architecture for integrating heterogeneous knowledge sources:
independent specialists ("knowledge sources") post partial results to a shared
blackboard; an integrator forms the solution. Two design invariants proved out
over decades:

1. **Knowledge sources are anonymous to the integrator** — control/synthesis
   never encodes source-specific logic; each source declares its own
   contribution conditions.
2. **Integration happens over the blackboard's contents**, i.e. over *what
   actually arrived*, not over what the query predicted would arrive.

Mapping: Mira's fan-out results list *is* a blackboard; facets are knowledge
sources. Invariant 1 → synthesis must not name domains (rules travel with the
source: `synthesis_hint`). Invariant 2 → specialization by **composition of
results** (D2-c), not by question (D2-b).

### 3.2 Mixture of Experts (Jacobs & Jordan 1991 → modern MoE)

MoE separates three concerns cleanly: a **gating** function selects experts, the
experts compute independently, and a **generic combiner** merges outputs. The
combiner never contains expert-specific logic. Fifty years of blackboards and
thirty of MoE agree: *selection* and *combination* are different mechanisms,
and combination stays generic. This is D3 ≠ D1 in the wild.

### 3.3 Production multi-agent systems (2025–26)

[Anthropic's multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
is the most instructive production datapoint: an orchestrator-worker design
where a lead agent spawns parallel subagents, each returning **compressed
findings**, and the **lead alone synthesizes** (with a dedicated citation pass).
Findings that transfer to Mira:

- Parallel workers exist for *breadth*; the final judgment is one context —
  splitting synthesis across workers loses the cross-source comparisons that
  are the system's whole value. (90.2% improvement over single-agent came from
  parallel *search*, not parallel *synthesis*.)
- Each worker needs a strict contract (objective, output format, boundaries) —
  Mira's facet contract (one tool, attributed envelope, structured degradation)
  is exactly this.
- Workers *condense* before the lead synthesizes — this is the scaling shape
  (D1-c) to adopt when payloads outgrow one context, not before.

[LangGraph's multi-agent taxonomy](https://reference.langchain.com/python/langgraph-supervisor)
(supervisor / network / hierarchical) makes the same point structurally:
hierarchies of supervisors are the *overflow valve* for when one supervisor's
context or tool space saturates — "overkill for most teams" until then.

### 3.4 A2A agent cards

The [A2A protocol](https://a2a-protocol.org/latest/specification/) settles
*where* domain metadata belongs: on a declarative, machine-readable card
(identity, skills, capabilities) so that orchestrators integrate agents
**without hard-coded integrations**. Mira's `AgentCard` is already A2A-shaped
(ADR-035). Extending the card (`model_hint` per ADR-052, now
`synthesis_hint`, proposed `analyze_group`) rides the industry direction; a
hardcoded fan-out tuple fights it.

## 4. Option analysis with failure modes

### D1 — synthesis ownership

**(a) Per-domain synthesizers.** Each family owns end-to-end synthesis.
- *For:* domain voice; independent evolution (Conway-aligned if separate teams
  own families); per-family output formats.
- *Failure modes:* (i) **cross-domain conflict is structurally unresolvable** —
  when technical says CLOSE and thesis says INTACT, two synthesizers emit two
  takeaways and a meta-synthesizer must be reintroduced, recreating D1 one
  level up; (ii) the grounding contract (never fabricate, cite provenance) is
  duplicated N times and *will* drift — a provenance leak in one family's
  prompt is a governance hole; (iii) N deep-tier calls per analysis; (iv) N
  prompts to eval-gate (multiplies the ADR-045 gate surface).
- *Verdict:* correct only when domains never co-occur in one question. Mira's
  analyze flow exists precisely because they do.

**(b) One shared synthesizer.** All forces reversed: one grounding contract,
one deep-tier call, conflicts resolved in one context, one eval surface.
- *Failure mode:* context saturation as domains multiply — bounded today
  (≤1,400 chars/domain digest × 7 domains ≈ 10KB; deep-tier context is 100×
  that), and the measured escape is (c).

**(c) Hierarchy (condensers → global synthesizer).** Not an alternative to (b)
but its scaling mode — exactly Anthropic's compress-then-synthesize. Adopt when
the digest budget forces truncation (observable: `_truncated` keys appearing in
prompts), not speculatively.

### D2 — specialization mechanism

**(b) By question** creates a second, hidden router that can disagree with the
first: the supervisor/fan-out already decided *who participates* from the
question; re-deriving domain identity from question text at synthesis time can
contradict what the results actually contain (question says "valuation," but
the thesis facet returned the decisive fact). It is also either brittle
(keywords) or nondeterministic (LLM classification) — the latter breaks the
repo's deterministic eval gates.

**(c) By composition of results** is deterministic (identity = f(what
returned)), honors blackboard invariant 2, and makes the synthesizer *become*
a portfolio analyst when portfolio domains answer and a health analyst when
health domains answer — with zero synthesis-code knowledge of either. The
implementation is the card-carried `synthesis_hint` assembled per-call for
present domains.

- *Failure modes & containment:* (i) two cards give conflicting guidance →
  hints are scoped by contract to "how *this domain's* results may be used,"
  never to other domains; (ii) one bad hint degrades output → hints are data,
  diffable and eval-gateable per card; (iii) unbounded hint growth → see the
  bloat loop in §5.

### D3 — participation selection

**(a) Static tuple:** fails open-closed; the current state.
**(b) Registry groups** (`analyze_group` on cards): declarative, deterministic,
A2A-aligned; new family = register cards, zero pipeline edits. Selection order
= registration order (already meaningful in `build_live_registry`).
**(c) LLM planner:** reads the question + card catalog, emits the domain set.
Most flexible; nondeterministic, un-eval-gateable today, and — decisive —
**layerable later behind the same interface** (a planner is just another
producer of the domain list the fan-out API already accepts). Choosing (b) now
forecloses nothing.

## 5. Systems dynamics

**Leverage points** (Meadows' hierarchy, weakest → strongest, applied here):

- *Parameters* — editing prompt text per domain: the treadmill the user
  rejected. Weakest leverage; the original sin.
- *Information flows* — domain rules travel on cards to the synthesizer:
  changes who knows what, without changing structure. This is `synthesis_hint`.
- *Rules/structure* — who participates is registry data, not code: changes how
  the system self-organizes. This is `analyze_group`.
- *Paradigm* — "portfolio analysis" reframed as *first instance of a generic
  subject × group analysis operation*. Highest leverage: every later family
  inherits the machinery for free.

**Feedback loops to manage:**

1. *Hint-bloat loop (reinforcing):* domains added → hints accumulate → prompt
   grows → synthesis quality decays → per-domain "fixes" add more hint text.
   Balancing intervention: hint length is card-reviewable data; the condenser
   tier (D1-c) is the pressure valve, triggered by observed truncation.
2. *Eval-governance loop (balancing, protective):* with synthesis behavior as
   card data, a domain's rule change is a diffable artifact the ADR-045 eval
   gate can hold; per-domain synthesizers would multiply that surface N-fold
   and weaken the gate.
3. *Failure containment (existing, preserved):* a facet's tool failure degrades
   to a structured observation which the generic contract forces synthesis to
   *report* ("say so plainly"). In per-domain synthesis, a failed family is
   silent — an absence, not a statement, invisible to the reader.

## 6. Decision

- **D1 = (b)** one shared synthesizer; **(c)** condensers only when digest
  truncation is observed in practice.
- **D2 = (c)** composition-specialized via card-carried hints (implemented).
- **D3 = (b)** registry groups on cards (`analyze_group`); planner (c) is a
  compatible later layer, gated on an eval story for nondeterministic routing.

**Falsifiable evolution triggers** (so this decision self-revises instead of
ossifying):

| Trigger (observable) | Evolution |
|---|---|
| `_truncated` digests appear in synthesis prompts | add light-tier condenser nodes per domain (D1-c) |
| Two groups need materially different *personas*, not just rules | card-declared synthesis persona, same mechanism |
| Cross-group questions become common | planner-produced domain lists behind the existing fan-out API (D3-c) |
| A family needs domain-specific *output format* | per-group format hint on cards, not a new synthesizer |

## 7. Implications for the in-flight work

Already aligned: generic contract + `synthesis_hint` (D2-c), parallel
`StateGraph` over an arbitrary domain list (D1-b substrate).

Remaining to align: replace `DEFAULT_ANALYZE_DOMAINS` + ticker-typed `symbol`
with card-declared `analyze_group` + group-validated `subject` (D3-b). This is
the last "modification" row in §2's table; until it lands, every new family
re-opens `analyze.py`.

## Sources

- [How we built our multi-agent research system — Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Multi-agent coordination patterns — Claude/Anthropic](https://claude.com/blog/multi-agent-coordination-patterns)
- [LangGraph multi-agent supervisor reference](https://reference.langchain.com/python/langgraph-supervisor)
- [A2A Protocol specification (Agent Cards)](https://a2a-protocol.org/latest/specification/)
- [A2A agent discovery](https://a2a-protocol.org/latest/topics/agent-discovery/)
- Erman, Hayes-Roth, Lesser, Reddy — *The Hearsay-II Speech-Understanding
  System* (ACM Computing Surveys, 1980) — blackboard architecture invariants.
- Jacobs, Jordan, Nowlan, Hinton — *Adaptive Mixtures of Local Experts*
  (Neural Computation, 1991) — gating/combination separation.
