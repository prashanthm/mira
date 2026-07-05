# ADR-011: Model Fallback & Cost/Quota Routing

## Status

Accepted

## Context

The model gateway ([ADR-010](./adr-010-provider-agnostic-model-gateway.md)) is the single place all
model calls pass through, and it explicitly **defers the fallback chain and cost/quota routing
policy to this ADR**. The product brief commits MIRA-MODEL to "resilient, cost-controlled model
access… fallback models, cost/quota routing." This ADR decides *what that policy is*: how the
gateway behaves on provider error/throttle/budget, and how it routes for cost/quota — without
leaking provider choice into business logic.

It conforms to the locked architecture: the policy lives **inside the gateway behind `ILLMProvider`**
([ADR-002](./adr-002-provider-abstraction-pattern.md)), framework-agnostic ([ADR-007](./adr-007-core-agent-stack-and-framework.md)
containment); cost/latency telemetry uses the OTel GenAI spans ([ADR-042](./adr-list.md), inherited
MCP-server ADR-013 — metrics & tracing); and provider 429 is a
fallback signal, **not** a re-implementation of the MCP-boundary rate limiting (inherited
MCP-server ADR-008 — rate-limiting strategy).

## Decision Drivers

1. **MIRA-MODEL** — resilient (survive provider outage) + cost-controlled model access.
2. **ADR-010 deferral** — the gateway owns this; this ADR fills in the fallback + routing policy.
3. **Provider outages are real** — one provider's 5xx/timeout must not become a full outage.
4. **Cost governance (NIST AI RMF MANAGE)** — cost/quota as a managed control with budget caps.
5. **ADR-007 containment** — policy is framework-agnostic, behind `ILLMProvider`.

## Research & Rubric

`Research & rubric — ADR-011`. Scored a named multi-strategy fallback + cost-aware routing policy in the gateway vs single-provider retry-only vs an external-router-only path against outage survival, cost/quota control, graceful degradation, ADR-010/007 fit, and telemetry reuse. The in-gateway multi-strategy policy wins — it is the canonical 2026 LLM-gateway pattern (retry→fallback→circuit-breaker + cost-aware routing) and lives behind `ILLMProvider`. Self-contained on LLM-gateway/resilience practice + NIST; internal ADRs fix where it plugs in.

## Decision

Adopt a **named multi-strategy fallback chain with a circuit breaker, plus cost-aware routing and
budget caps**, all inside the gateway behind `ILLMProvider`.

**1. Fallback chain (ordered, configurable, mixed-tier)**
- **Retry-then-fallback:** exponential-backoff retry against the primary first; only fail over after
  the retry budget is exhausted.
- **Provider-rotation** on 5xx / network error / hard timeout — cycle to the next provider in the chain.
- **Model-downgrade** on 429 / budget-cap hit / context-window overflow — swap to a cheaper/alternate model.
- **Circuit breaker** isolates a failing provider (trip on sustained failures, half-open probe to
  reset) so one outage doesn't cascade.
- **Cache-on-failure / manual-route** as last resorts — return a safe cached response, or hand off to
  a degraded mode / human ([ADR-039](./adr-list.md)) when no provider can serve within the latency budget.
- The chain is **profile-configurable** (e.g. an on-prem profile may have a single provider; mixed
  cloud tiers otherwise). Provider/model SDKs stay in `providers/` ([ADR-010](./adr-010-provider-agnostic-model-gateway.md) containment).

**2. Cost/quota routing**
- A configurable **routing strategy** — **cost-based** (cheap-first, escalate on need), **latency-based**,
  or **usage/quota-aware** — selects the provider/model/key per request.
- **Budget caps** (per tenant/agent/time-window) are enforced; exceeding a cap triggers model-downgrade
  or rejection, surfaced as a managed signal, with **cost attributed via OTel spans** ([ADR-042](./adr-list.md)).

**3. Boundaries (restating ADR-010)**
- All of the above is **gateway-internal, behind `ILLMProvider`**; callers/business logic never see
  providers or fallback. A managed router (e.g. LiteLLM/Portkey) is a permissible *implementation*
  behind the Protocol, never the architecture or a leaked dependency.
- Provider **429/throttle is a fallback/backoff signal**; per-user/per-IP rate limiting remains at the
  MCP tool boundary (inherited MCP-server ADR-008 — rate-limiting strategy).

**Rejected alternatives:**

- **Single-provider, retry-only (no fallback/routing)** — Rejected: a provider outage becomes a full
  outage; no cost control beyond the model choice.
- **External router service as the only path** — Rejected as the architecture: a hard third-party
  dependency + extra hop; still needs the `ILLMProvider` seam in front (allowed as a gateway impl).
- **Fail-fast, no retry** — Rejected: transient 5xx/timeouts are common; no-retry wastes the cheapest
  recovery and worsens reliability.

## Consequences

### Becomes Easier

- A single-provider outage degrades gracefully (rotation + circuit breaker) instead of failing the request.
- Cost is controlled as a managed risk — cheap-first routing + budget caps + attributed spans.
- Policy is one configurable place behind `ILLMProvider`; profiles tune the chain (incl. single-provider on-prem).
- Reuses OTel cost telemetry (ADR-042) and the inherited 429 boundary; nothing re-implemented.

### Becomes Harder

- A multi-strategy chain + breaker + routing is real logic to build, test, and tune (thresholds,
  budgets, breaker timings).
- Cache-on-failure must be proven safe (staleness/grounding) — likely limited to idempotent calls.
- Quota-aware routing needs live per-provider quota signals, which vary by provider.

## Applies To

- **MIRA-MODEL** — fallback & cost/quota routing (primary)
- [ADR-010](./adr-010-provider-agnostic-model-gateway.md) — the gateway this policy lives inside
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — framework-agnostic, behind the Protocols
- [ADR-042](./adr-list.md) — cost-attribution spans; [ADR-012](./adr-list.md) — downgrade↔prompt-version compatibility
- [ADR-039](./adr-list.md) (manual-route / HITL) / [ADR-044](./adr-list.md) (incident on sustained failover)
- Inherited: MCP-server ADR-008 (429 boundary), MCP-server ADR-013 (OTel)

## Links

- ADR file: `docs/adr/adr-011-model-fallback-cost-routing.md`
- Research & rubric: `research/adr-011-model-fallback-cost-routing.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-011
- Epic: MIRA-MODEL
