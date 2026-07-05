# ADR List — Mira

> Catalog of architecture decisions for **Mira**, a domain-agnostic reference agentic-AI
> implementation (Python package `mira`). Mira is source-agnostic agentic AI over heterogeneous
> data: every data source is a pluggable connector, and no single source is the foundation. The
> two demo domains are `research` (Markdown docs connector) and `finance` (CSV ledger connector).
>
> Decisions marked **(pending ADR)** in the summary are genuinely open — the full ADR will record
> why the current direction was picked or not. Decisions stated directly are committed by the
> project charter; their full ADRs still record rationale and alternatives.

## Inherited constraints

Decisions at the MCP server boundary — tool-transport protocol, caller authentication and token
validation, rate limiting, structured logging and correlation-ID propagation, and entitlements
enforcement for tool/data access — are owned by the MCP tool server Mira consumes. Mira inherits
them as fixed constraints and does **not** re-decide them in this catalog; local ADRs only layer
agent-side concerns (per-agent identity, task-scope narrowing, agent-layer resilience, telemetry
extensions) on top of that boundary.

## ADRs — Mira

ADRs 001–014, 017–027, 031–035, 037, and 045–048 are **Accepted**. ADR-036 and the twelve
pending ADRs (015, 016, 028–030, 038–044) are **Proposed**; each pending ADR has a stub linked
below. Summaries are one decision-oriented sentence; `(Phase X)` marks decisions the roadmap
defers: **B** supervisor + evals, **C** retrieval (028–030), **D** safety & trust (036, 038–041),
**E** AgentOps (042–044), **F** dynamic composition (015, 016). `(pending ADR)` marks decisions
whose direction is not yet committed.

### Foundation & Platform

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-001 | [Repository Structure & Provider-Isolation Layout](./adr-001-repository-structure-and-provider-isolation-layout.md) | Accepted | Ship a single `mira` repository (Python package `mira`) with cloud-SDK access confined to `/providers/` behind Protocol interfaces, enforced by a linter/CI import rule. |
| ADR-002 | [Provider Abstraction Pattern](./adr-002-provider-abstraction-pattern.md) | Accepted | Access platform capabilities through `PLATFORM`-env-driven factories over five Protocol interfaces (ILLMProvider, ISecretsProvider, IObjectStore, IStateStore, IObservability) so business logic stays cloud-agnostic. |
| ADR-003 | [Branching Strategy & Repo Workflow](./adr-003-branching-strategy-and-repo-workflow.md) | Accepted | Select the branching model and PR/CI rules; trunk-based development with short-lived feature branches is the current direction (pending ADR). |
| ADR-004 | [Compliance Conformance — License, Signed Commits & Dependency Scanning](./adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md) | Accepted | Conform to the shared delivery-process gates by enforcing the license policy, signed commits, and dependency scanning in this repo's CI. |

### Clients & Entry Points

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-005 | [Client Surface Boundary](./adr-005-client-surface-boundary.md) | Accepted | Define the user-facing surfaces (Agent Chat UI, demo console, portal + SSO via OIDC, SDK/typed client) and how each authenticates and what each is permitted to call. |
| ADR-006 | [API Design Standard for Agent-Facing Interfaces](./adr-006-api-design-standard-for-agent-facing-interfaces.md) | Accepted | Select the agent-facing HTTP/WebSocket, streaming + live-plan, `/explain`, and webhook conventions distinct from the inherited MCP tool API (pending ADR). |

### Agent Core & Runtime (L02)

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-007 | [Core Agent Stack & Framework](./adr-007-core-agent-stack-and-framework.md) | Accepted | Keystone: adopt **LangGraph** (durable execution, `recursion_limit` loop bounds) behind ILLMProvider with a containment rule (langchain confined to the orchestration layer; CI lint extended), plus the tool-coherence contract and decision order the dependent agent-core ADRs conform to. |
| ADR-008 | [Agent Runtime Persistence & Warm-Start Model](./adr-008-runtime-persistence-warm-start.md) | Accepted | Run a persistent (warm) agent runtime with health/readiness probes and graceful shutdown rather than cold per-request invocation. |
| ADR-009 | [Middleware Pipeline Architecture](./adr-009-middleware-pipeline-architecture.md) | Accepted | Wrap every agent request in a composable, ordered middleware pipeline (auth → correlation → entitlement → guardrail-in → LangGraph execution → guardrail-out → telemetry) as the single enforcement chokepoint; framework-agnostic per the ADR-007 containment rule, generalizing the ADR-033 chokepoint. |
| ADR-010 | [Provider-Agnostic Model Gateway](./adr-010-provider-agnostic-model-gateway.md) | Accepted | Route all model calls through a central gateway behind ILLMProvider (fallback, cost/quota routing, prompt-version resolution, token/cost spans); LangGraph reaches it via a thin BaseChatModel adapter, vendor SDKs confined to `providers/` per ADR-007 containment. |
| ADR-011 | [Model Fallback & Cost/Quota Routing](./adr-011-model-fallback-cost-routing.md) | Accepted | In the ADR-010 gateway: a named multi-strategy fallback chain (retry-then-fallback, provider-rotation, model-downgrade, cache/manual) with a circuit breaker, plus cost-aware routing (cost/latency/quota) and budget caps — all behind ILLMProvider; 429 is a fallback signal, rate limiting stays at the MCP boundary. |
| ADR-012 | [Prompt & Tool Versioning with Staged Rollout & Kill Switch](./adr-012-prompt-tool-versioning.md) | Accepted | Version prompts & tool defs as first-class artifacts in a registry behind the Protocol seam; promote dev→staging→prod, eval-gated canary rollout (ADR-045), and a runtime kill switch for instant code-deploy-free rollback; version resolved at the ADR-010 gateway. |
| ADR-013 | [Reasoning Pattern & Loop-Safety Bounds](./adr-013-reasoning-pattern-and-loop-safety.md) | Accepted | ReAct (plan/act/observe/reflect) as LangGraph nodes/edges with layered hard bounds (recursion_limit + token/time/cost ceilings + interrupt() HITL gates); durable waits don't count as loop steps. |
| ADR-014 | [Domain-Agent & Supervisor Routing Model](./adr-014-domain-agent-supervisor-routing.md) | Accepted | Supervisor (orchestrator-worker) on LangGraph subgraphs routes to domain specialists (`research` and `finance` demo agents; each a state-isolated subgraph running the ADR-013 loop, an identity boundary, discoverable via agent cards); single auditable control flow with hierarchical failure boundaries. |
| ADR-015 | [Dynamic Workflow Composition](./adr-015-dynamic-workflow-composition.md) | Proposed | Select how multi-step workflows are composed from discoverable agents and skills via supervisor routing (pending ADR) (Phase F). |
| ADR-016 | [Agent Scaffolding & Generation](./adr-016-agent-scaffolding-and-generation.md) | Proposed | Select how new domain agents are generated from a spec with identity, agent card, and eval baseline wired at creation (pending ADR) (Phase F). |
| ADR-017 | [Memory Architecture](./adr-017-memory-architecture.md) | Accepted | Three-tier working/session/long-term memory: LangGraph checkpointer behind IStateStore for durable session state, a framework-agnostic retrievable long-term store behind the ADR-002 seams, and summarization-based compression; integrity/embedding-versioning deferred to ADR-018. |
| ADR-018 | [Memory Integrity & Embedding Versioning](./adr-018-memory-integrity-and-embedding-versioning.md) | Accepted | Write-time provenance + trust-gated ingestion for the long-term memory tier, plus version-tagged embeddings behind a stable alias with parallel-index-then-swap re-embedding on model upgrade. |

### Source-Agnostic Data Fabric (L03)

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-019 | [Federation Strategy — Aggregate vs Federate](./adr-019-federation-strategy-aggregate-vs-federate.md) | Accepted | Record the aggregate-vs-federate rule the charter requires; query-in-place virtualization with selective lakehouse aggregation for analytical/RAG workloads is the current direction (pending ADR). |
| ADR-020 | [Source Connector Architecture](./adr-020-source-connector-architecture.md) | Accepted | Implement source connectors (Markdown docs, CSV ledger, and future domain sources) as adapters behind the MCP tool surface so every source is one optional connector among many. |
| ADR-021 | [Storage Engine Selection](./adr-021-storage-engine-selection.md) | Accepted | Role-based polyglot persistence behind the ADR-002 Protocols: four roles (knowledge-graph, vector index, state/cache, relational) with engines as per-profile defaults (not commitments), each with a portable on-prem default — honoring ADR-019's "engines illustrative only"; governs only the selectively-aggregated data. |
| ADR-022 | [Canonical Entity Resolution & Identity](./adr-022-canonical-entity-resolution-and-identity.md) | Accepted | Deterministic-key-first canonical entity resolution, materialized as canonical identity nodes in the ADR-021 knowledge-graph store role. |
| ADR-023 | [Unit-of-Measure Normalization](./adr-023-unit-of-measure-normalization.md) | Accepted | Dedicated unit-of-measure normalization component keyed to a published UoM standard, consuming the tool surface's existing `_llm_context`/frame-of-reference metadata rather than re-deriving it. |
| ADR-024 | [CRS/Datum Preservation & Coordinate-Operation Audit Trail](./adr-024-crs-datum-preservation-and-coordinate-operation-audit-trail.md) | Accepted | Permanent preservation of each source dataset's original reference-system declaration plus a structured, append-only operation log for every transform performed. |
| ADR-025 | [Interpretation-vs-Measurement & Multi-Source Conflict Surfacing](./adr-025-interpretation-vs-measurement-and-multi-source-conflict-surfacing.md) | Accepted | Tagged value model with mandatory `kind` classification (measurement vs interpretation) and explicit multi-source conflict surfacing — never silently picks a winner. |
| ADR-026 | [Catalog Service Design](./adr-026-catalog-service-design.md) | Accepted | Dedicated catalog service, architecturally distinct from the knowledge-graph spine, using an entity + pluggable-aspect metadata model. |
| ADR-027 | [Knowledge-Graph Semantic Catalog Spine](./adr-027-knowledge-graph-semantic-catalog-spine.md) | Accepted | RDF/OWL as the graph model for the ADR-021 knowledge-graph store role, ontology seeded from an open reference ontology. |
| ADR-028 | [Hybrid Retrieval Pipeline](./adr-028-hybrid-retrieval.md) | Proposed | Select the retrieval approach (hybrid dense + sparse, re-ranking, query expansion, multi-KB); hybrid + RRF + cross-encoder is the current direction (pending ADR) (Phase C). |
| ADR-029 | [Agentic RAG Strategy](./adr-029-agentic-rag.md) | Proposed | Select the agentic retrieval strategy; Self-RAG / Corrective-RAG loops are the current direction (pending ADR) (Phase C). |
| ADR-030 | [Graph + Vector Fusion (Graph RAG)](./adr-030-graph-vector-fusion.md) | Proposed | Select the graph-plus-vector fusion approach (document-KG with source linking and community detection) for entity-aware grounding (pending ADR) (Phase C). |
| ADR-031 | [Typed Tool Contracts](./adr-031-typed-tool-contracts.md) | Accepted | Agent tools are typed MCP contracts: flat JSON Schema inputSchema + tool annotations (readOnly/idempotent/destructive/openWorld) + idempotency keys/retry/timeout + declared authorization; conforms to the inherited MCP tool surface, versioned by ADR-012, enforced in ADR-009, authz enforced at the MCP boundary. |
| ADR-032 | [Skills Registry, Versioning & Authorization](./adr-032-skills-registry-versioning-and-authorization.md) | Accepted | Skills register as a new versioned artifact kind in the ADR-012 registry: a named, composed capability built from one or more ADR-031 typed tool contracts. |

### Governance, Security & Trust (L01)

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-033 | [Phase 1 Minimum Identity Slice](./adr-033-phase-1-minimum-identity-slice.md) | Accepted | Ship an initial service identity carrying per-call tenant/user/correlation attribution and MCP-scoped entitlements as the interim least-privilege model. |
| ADR-034 | [Per-Agent Identity & Task-Scoped Tokens](./adr-034-per-agent-identity-and-task-scoped-tokens.md) | Accepted | OAuth 2.0 Token Exchange (RFC 8693) mints a short-lived, task-scoped token per specialist dispatch, replacing the shared initial service identity. |
| ADR-035 | [Agent Cards & A2A Discovery](./adr-035-agent-cards-and-a2a-discovery.md) | Accepted | A2A `AgentCard` schema for specialist/supervisor discovery metadata, published at a well-known URI, discovered via direct/private configuration. |
| ADR-036 | [Prompt-Injection & Tool-Abuse Defense](./adr-036-prompt-injection-and-tool-abuse-defense.md) | Proposed | Select the prompt-injection and unauthorized-tool-use defense for the agent boundary (pending ADR) (Phase D — coupled to per-agent identity; the full bidirectional guardrail pipeline is ADR-037). |
| ADR-037 | [Bidirectional Guardrail Pipeline](./adr-037-bidirectional-guardrail-pipeline.md) | Accepted | Custom bidirectional (input+output) guardrail pipeline in the ADR-009 guardrail-IN/-OUT stages as the primary control, with an optional cloud guardrail service as a secondary defense-in-depth layer; portable to on-prem, framework-agnostic; composes ADR-036/038/039. |
| ADR-038 | [Hallucination & Topic-Drift Controls](./adr-038-hallucination-and-topic-drift-controls.md) | Proposed | Select the hallucination-detection and topic-drift/domain-scope controls, recognizing grounding is necessary but not sufficient (pending ADR) (Phase D). |
| ADR-039 | [Human-in-the-Loop Escalation](./adr-039-hitl-escalation.md) | Proposed | Escalate high-risk actions to a human at the request boundary; an async webhook callback integrated with ticketing/chat tooling is the current mechanism direction (pending ADR) (Phase D). |
| ADR-040 | [Decision-Trace Audit Model](./adr-040-decision-trace-audit.md) | Proposed | Link every factual claim to source records via decision traces; an append-only attribution store is the current direction (pending ADR) (Phase D). |
| ADR-041 | [Explanation API & Uncertainty Quantification](./adr-041-explanation-api-and-uncertainty.md) | Proposed | Select the `/explain` API and uncertainty-quantification design exposing multi-level explanations (pending ADR) (Phase D). |

### Observability & Eval (cross-cutting)

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-042 | [AgentOps Telemetry & LLM Cost Attribution](./adr-042-agentops-telemetry-and-llm-cost-attribution.md) | Proposed | Extend the inherited OpenTelemetry stack with LLM cost-attribution spans, cost dashboards/alerting, and anomaly detection; the exact span/cost-model design is pending ADR (Phase E). |
| ADR-043 | [SLOs & Error Budgets](./adr-043-slos-and-error-budgets.md) | Proposed | Define the agent surface's SLOs and error budgets (latency, cost, error rate) as the operability target (pending ADR) (Phase E). |
| ADR-044 | [Incident Detection & Remediation Workflow](./adr-044-incident-detection-and-remediation.md) | Proposed | Select the anomaly-triggered incident detection and escalation workflow for production AgentOps (pending ADR) (Phase E). |
| ADR-045 | [Eval Framework & CI Safety Gate](./adr-045-eval-framework-ci-safety-gate.md) | Accepted | Blocking golden + adversarial CI gate, run by a pytest-orchestrated, trace/OTLP-based suite using a pytest-native OSS eval library (DeepEval) — framework-agnostic per ADR-007 containment, not LangSmith; asserts claim→source linkage via decision traces. |
| ADR-046 | [Agent-Layer Resilience Policy](./adr-046-agent-layer-resilience.md) | Accepted | Define agent-layer resilience (model-gateway circuit-breaking/backoff, reasoning loop safety, runtime health), explicitly deferring MCP→source call-path resilience to the inherited MCP tool server (pending ADR). |

### Deployment & Substrate (L04)

| ID | Title | Status | Summary |
|----|-------|--------|---------|
| ADR-047 | [Deployment Profiles & Packaging](./adr-047-deployment-profiles-and-packaging.md) | Accepted | Ship the same artifact across managed SaaS, standalone, AWS Outposts, and customer Kubernetes via deployment profiles; the packaging path (Helm/operator) and profile mechanism are pending ADR. |
| ADR-048 | [Secure Cloud Runtime & Network Isolation](./adr-048-secure-cloud-runtime-and-network-isolation.md) | Accepted | Select the secure runtime and network isolation model; VPC private mode, WAF, restricted egress, and ECS Fargate/EKS are the current direction (pending ADR). |
