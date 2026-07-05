# ADR-010: Provider-Agnostic Model Gateway

## Status

Accepted

## Context

The product brief commits to "provider-agnostic model access: fallback models, cost/quota routing,
prompt versioning" (MIRA-MODEL). [ADR-002](./adr-002-provider-abstraction-pattern.md) fixes
`ILLMProvider` as the seam and forbids vendor SDKs outside `providers/`;
[ADR-007](./adr-007-core-agent-stack-and-framework.md) selects LangGraph with a **containment rule**
(no `langchain*` in business logic; framework swappable). This ADR decides how model calls are
routed so that LangGraph and business logic never touch a vendor SDK, and there is one place for
fallback, cost/quota routing, and prompt-version resolution.

## Decision Drivers

1. **MIRA-MODEL** — fallback models, cost/quota routing, prompt versioning need a single home.
2. **ADR-002 isolation** — model access via `ILLMProvider`; vendor SDKs only in `providers/`.
3. **ADR-007 containment** — LangGraph must reach models without importing vendor SDKs into the
   orchestration layer.
4. **Cost governance** — NIST AI RMF MANAGE: centralized routing makes cost/quota a managed control.
5. **Telemetry** — token/cost/latency spans belong at the model-call boundary (OpenTelemetry GenAI).

## Research & Rubric

Research & rubric: `research/adr-010-provider-agnostic-model-gateway.md`. Scored a central gateway behind `ILLMProvider` vs direct LangGraph→provider chat models vs an external proxy-only path against fallback/cost routing, prompt-versioning, vendor-SDK isolation (ADR-007 containment), telemetry, and testability. The gateway wins — it is the gateway/anti-corruption pattern, the single place for routing/cost/prompt-version, and lets LangGraph reach models via a thin `BaseChatModel` adapter with SDKs confined to `providers/`. Self-contained on the gateway pattern + OTel/NIST; internal ADRs fix where it plugs in.

## Decision

Route **all** model calls through a **central model gateway behind `ILLMProvider`**. No business-logic
or orchestration code calls a vendor model SDK directly.

**Shape:**

- **`ILLMProvider` is the contract** ([ADR-002](./adr-002-provider-abstraction-pattern.md)): chat/completion, embeddings, streaming tokens. The gateway is the production implementation; tests use a Protocol mock.
- **Vendor SDKs live only in `providers/`** — `providers/aws/llm.py` (Bedrock), `providers/<x>/llm.py`, or a multi-provider router (e.g. LiteLLM) **as an implementation detail behind the Protocol**, never exposed upward.
- **LangGraph reaches the gateway via a thin `BaseChatModel` adapter** that delegates to `ILLMProvider`. LangGraph/`langchain*` imports stay in the orchestration layer ([ADR-007](./adr-007-core-agent-stack-and-framework.md) containment); the adapter is the only bridge, and it depends on the Protocol, not on a vendor SDK.
- **Responsibilities of the gateway:** provider selection; **fallback chain** and **cost/quota routing** (policy detail → [ADR-011 (Proposed)](./adr-011-model-fallback-cost-routing.md)); **prompt-version resolution** (versioning/rollout/kill-switch → [ADR-012 (Proposed)](./adr-012-prompt-tool-versioning.md)); **token/cost/latency telemetry** as OTel GenAI spans (inherited MCP-server ADR-013; ADR-042 (Proposed) — see [adr-list.md](./adr-list.md)); pass-through token **streaming** for the [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) SSE path.
- **Throttling:** provider 429/throttle is a fallback/backoff signal; per-user/per-IP rate limiting stays at the MCP tool boundary (inherited MCP-server ADR-008), not re-implemented here.

**Rejected alternatives:**

- **Direct LangGraph→provider chat models** (`ChatBedrock`/`ChatOpenAI` directly) — Rejected: scatters
  provider choice, no central fallback/cost/prompt-versioning, and pulls vendor SDKs into the
  orchestration layer against ADR-007 containment.
- **External LLM proxy as the only path** — Rejected as the architecture (allowed as a *provider
  implementation*): a separate proxy process adds an operational hop and still needs the
  `ILLMProvider` seam in front for isolation/testability. ADR-011 should restate this boundary
  explicitly — a proxy (e.g. LiteLLM) is a valid `providers/` implementation detail, not the
  architectural seam; `ILLMProvider` is.
- **Per-call provider selection in business logic** — Rejected: leaks provider concerns and cost
  policy throughout the codebase; defeats the single-home requirement.

## Consequences

### Becomes Easier

- One place for fallback, cost/quota routing, prompt-version resolution, and token/cost telemetry.
- LangGraph (and any future framework) reaches models without importing a vendor SDK — containment holds.
- Multi-provider / on-prem (Bedrock, Anthropic, Ollama, …) is a `providers/` concern, swappable per profile.
- Tests mock `ILLMProvider`; no network or vendor SDK in unit tests.

### Becomes Harder

- The `BaseChatModel` adapter must track LangGraph's chat-model interface as it evolves (one bridge to maintain).
- Streaming + tool-calling semantics must be faithfully mapped through the gateway/adapter.
- A central gateway is a hot path — its latency/availability is now load-bearing (mitigated by fallback).

## Applies To

- **MIRA-MODEL** — model gateway (primary)
- **MIRA-RUNTIME** / **MIRA-REASON** — consumers via `ILLMProvider`
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — containment (adapter is the only langchain bridge)
- [ADR-002](./adr-002-provider-abstraction-pattern.md) — `ILLMProvider` contract
- [ADR-011 (Proposed)](./adr-011-model-fallback-cost-routing.md) — fallback & cost/quota routing policy; [ADR-012 (Proposed)](./adr-012-prompt-tool-versioning.md) — prompt versioning
- ADR-042 (Proposed; see [adr-list.md](./adr-list.md)) — cost-attribution spans the gateway emits
- Inherited: MCP-server ADR-008 (rate limiting strategy), MCP-server ADR-013 (metrics & tracing)

## Links

- ADR file: `docs/adr/adr-010-provider-agnostic-model-gateway.md`
- Research & rubric: `research/adr-010-provider-agnostic-model-gateway.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-010
