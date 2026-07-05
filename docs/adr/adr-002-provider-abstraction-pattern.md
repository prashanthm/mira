# ADR-002: Provider Abstraction Pattern

## Status

Accepted

## Context

[ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) establishes `/providers/` as the sole cloud-SDK import zone. This ADR records **how** platform capabilities are accessed: Protocol interfaces, a `PLATFORM`-driven factory, and startup-time provider resolution — implementing design decision **D1** and the `provider-abstraction` spec.

Mira must run on **hosted SaaS, standalone customer VPC, AWS Outposts, and customer Kubernetes** with the same container image. Direct Bedrock/boto3 calls in reasoning, memory, or fabric code would bind every epic to AWS and block profile-driven placement.

Key forces:

- **Five capability classes** recur across epics: LLM inference, secrets, object storage, durable state, observability — each appears in architecture L2–L4 diagrams.
- **Inherited telemetry/logging** — the inherited MCP-server ADR-011/012/013 fix structlog JSON + OTel; Mira extends via `IObservability`, does not replace.
- **Inherited secrets** — the inherited MCP-server ADR-006 defines a pluggable `SecretsBackend`; Mira aligns `ISecretsProvider` to the same backends per deployment profile.
- **Strands SDK / Bedrock** — the product brief named Strands on Bedrock as the then-current direction; isolation behind `ILLMProvider` keeps [ADR-007](./adr-007-core-agent-stack-and-framework.md) (framework selection) swappable.

## Decision Drivers

1. **Design decision D1** — "Protocol interfaces + factory pattern; structural typing; testable mocks."
2. **Initiative placement success criterion** — same artifact on SaaS, standalone, Outposts, K8s.
3. **PoC evaluation** — boto3 in 6+ non-provider modules; root cause of lock-in.
4. **MIRA-ARCH epic** — "Portable core without cloud SDK in business logic."
5. **Python 3.11+ structural typing** — `typing.Protocol` avoids heavy ABC hierarchies; matches the MCP tool server's async-first style.

## Decision

Access all platform capabilities through **five Protocol interfaces** resolved at startup by a **`ProviderFactory`** driven by the `PLATFORM` environment variable (default: `aws`). Business logic depends only on Protocol types injected via factory or FastAPI dependency injection.

**Protocol interfaces** (under `src/mira/interfaces/`):

| Protocol | Responsibility | Primary consumers |
|----------|----------------|-------------------|
| `ILLMProvider` | Chat/completion, embeddings, streaming tokens | MIRA-MODEL gateway, MIRA-REASON |
| `ISecretsProvider` | Resolve secrets by key/ARN | MIRA-ARCH middleware, all profiles |
| `IObjectStore` | Read/write blobs (artifacts, eval fixtures) | MIRA-FABRIC, MIRA-RAG (Phase 3) |
| `IStateStore` | Session + durable key-value (conversation state) | MIRA-RUNTIME, MIRA-MEMORY |
| `IObservability` | Structured logs, metrics, trace spans | Middleware pipeline ([ADR-009](./adr-009-middleware-pipeline-architecture.md)) |

**Factory resolution:**

```python
# src/mira/providers/factory.py (illustrative)
def build_providers(platform: str | None = None) -> ProviderBundle:
    platform = platform or os.environ.get("PLATFORM", "aws")
    match platform:
        case "aws":
            from mira.providers.aws import AwsProviderBundle
            return AwsProviderBundle.from_settings(settings)
        case "local":
            from mira.providers.local import LocalProviderBundle
            return LocalProviderBundle.from_settings(settings)
        case _:
            raise UnsupportedPlatformError(platform)
```

**Rules:**

1. **No vendor imports outside `providers/`** — enforced by ADR-001 CI rule.
2. **Single bundle per process** — providers resolved once at startup; no mid-request platform switch (same rationale as MCP-server ADR-027 rejecting runtime profile switching for auth/tool registration).
3. **`local` platform** — in-memory/fake implementations for unit tests and developer laptops; no cloud credentials required.
4. **Observability format** — `IObservability` implementations emit structlog JSON with secret redaction and OTel spans compatible with the inherited MCP-server conventions.
5. **LLM isolation** — Strands SDK / Bedrock client code lives only in `providers/aws/llm.py`; gateway and agents call `ILLMProvider` methods.

**Rejected alternatives:**

- **Direct boto3 in each module** — Rejected: PoC lock-in; untestable without AWS; violates D1.
- **Single mega-interface (`IPlatform`)** — Rejected: forces unrelated capabilities to share lifecycle; harder to mock selectively in tests.
- **Runtime plugin discovery (entry points)** — Rejected for Phase 1: adds packaging complexity before second platform is committed; factory `match` is sufficient until a third platform is funded.
- **Abstract base classes instead of Protocols** — Rejected: requires inheritance coupling; structural typing allows adapter wrappers without subclassing vendor clients.

## Consequences

### Becomes Easier

- Unit/integration tests run with `PLATFORM=local` — no AWS sandbox for most suites.
- Adding Azure/GCP becomes a new `providers/<vendor>/` package without epic-level refactors.
- Model gateway (MIRA-MODEL) and eval CI gate share one LLM abstraction.

### Becomes Harder

- Every new AWS service requires a Protocol method review — avoid leaking vendor-specific types into business logic signatures.
- Factory and settings must stay in sync as deployment profiles add dimensions — e.g. region, network placement, secrets/observability backend — detailed in [ADR-047 Deployment Profiles & Packaging](./adr-047-deployment-profiles-and-packaging.md).
- Two layers of indirection (factory → provider → SDK) adds startup debugging steps.

## Applies To

- **MIRA-ARCH** — primary epic
- **MIRA-MODEL** — gateway uses `ILLMProvider`
- **MIRA-RUNTIME** — `IStateStore`, middleware observability
- **MIRA-FABRIC** — `IObjectStore` for artifacts and eval fixtures
- **MIRA-MEMORY** — `IStateStore` for durable conversation state
- **MIRA-OBS** — `IObservability` extension for LLM cost spans (Phase 3)
- [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) — layout enforcement
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — agent framework selection (framework isolated behind `ILLMProvider`)
- Inherited: MCP-server ADR-006 (secrets backend abstraction), MCP-server ADR-011–013 (structured logging stack)

## Links

- ADR file: `docs/adr/adr-002-provider-abstraction-pattern.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-002
- Design decision D1: `provider-abstraction` spec (hardening spec set)
