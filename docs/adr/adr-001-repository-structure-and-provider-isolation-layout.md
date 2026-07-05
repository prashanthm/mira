# ADR-001: Repository Structure & Provider-Isolation Layout

## Status

Accepted

## Context

Mira ships as a **new runtime product** — multi-agent orchestration, a source-agnostic data fabric, and governed client surfaces — distinct from the **MCP tool server** boundary. The initiative charter commits to a dedicated **`mira` code repository**; decision records (ADRs), epics, and feature docs are tracked as files under `docs/` in this repository.

The predecessor PoC evaluation documented **complete AWS SDK lock-in** (boto3 imported throughout business logic), blocking the stated placement goals (SaaS, standalone, Outposts, customer Kubernetes). Design decision **D1 (Provider Abstraction)** and the `provider-abstraction` spec mandate Protocol interfaces with cloud SDKs confined to a `/providers/` tree.

Key forces:

- **Planning vs runtime separation** — planning docs (charter, ADRs, epics, features) live under `docs/`; runtime code needs its own package tree, CI, and release story.
- **Inherited MCP boundary** — agents consume MCP tool server tools; this repo owns orchestration, not the MCP protocol implementation (which remains in the MCP tool server repository).
- **Five-layer architecture** — agent experience, agent core, data fabric, security/identity, governance (see `docs/architecture/`) maps to top-level packages, not separate repos per layer.
- **Testability** — structural typing + factory pattern requires business logic that imports only Protocols, never boto3/azure SDKs.

## Decision Drivers

1. **Initiative charter** — "Implementation code lives in the **`mira` repository**."
2. **Design decision D1** — provider abstraction is Phase 1 scope; non-goal is *not* abstracting (abstraction is the first deliverable).
3. **PoC gap analysis** — AWS lock-in rated P0; provider isolation is the structural fix.
4. **Inherited MCP-server ADR-026/027** — Docker + Terraform IaC; one artifact with profile-driven placement extends to this repo's layout (`infra/` subdirectory precedent).
5. **Multi-epic Phase 1 surface** — MIRA-ARCH, MIRA-RUNTIME, MIRA-FABRIC, MIRA-CONNECTORS share one deployable service; monorepo-within-one-repo beats multi-repo fragmentation.

## Decision

Create GitHub repository **`prashanthm/mira`** with the following **top-level layout**. Cloud vendor SDK imports are **permitted only under `src/mira/providers/`** (enforced by CI lint rule `no-cloud-sdk-in-business-logic`, the D1 canonical name).

```
mira/
├── src/mira/
│   ├── interfaces/            # Protocol definitions (ILLMProvider, ISecretsProvider, …)
│   ├── providers/             # ONLY tree that may import boto3 / vendor SDKs
│   │   ├── factory.py         # PLATFORM-env-driven provider resolution
│   │   └── aws/               # AWS/Bedrock implementations
│   ├── runtime/               # Agent API, warm-start lifecycle, streaming
│   ├── gateway/               # Model gateway (calls ILLMProvider only)
│   ├── middleware/            # Per-request pipeline (auth, correlation, telemetry)
│   ├── fabric/                # Federation skeleton, connector adapters (MCP client)
│   ├── reasoning/             # Planner, loop safety (Phase 2+)
│   ├── memory/                # Session/long-term tiers (Phase 2+)
│   └── evals/                 # Golden + adversarial eval runner (pytest)
├── tests/
├── docs/
│   ├── adr/                   # Decision records (this catalog)
│   ├── architecture/          # System context, container diagrams (foundation-arch)
│   └── specs/                 # Implementation specs (AI-SDLC)
├── infra/                     # Terraform — profile-specific deployment (ADR-047)
├── deploy/
│   └── helm/                  # Customer Kubernetes / EKS packaging
├── .github/workflows/         # pr-gate, container build, eval gate
├── pyproject.toml
├── Dockerfile                 # Multi-stage, non-root (inherits MCP-server ADR-026 pattern)
└── README.md
```

**Concrete rules:**

1. **Decision records live in-repo** — `docs/adr/` holds ADRs; the charter, epics, and feature docs live under `docs/` alongside. The README links to the ADR catalog; there is exactly one copy of each ADR (no duplicate summaries elsewhere except references in `docs/architecture/`).
2. **Import boundary** — `ruff`/`import-linter` rule `no-cloud-sdk-in-business-logic` (design decision D1): modules under `src/mira/` except `providers/` must not import `boto3`, `botocore`, `azure.*`, `google.cloud.*`. CI fails on violation. Rule implementation lands with repo bootstrap (MIRA-PLACE / ADR-004); this ADR records the requirement only.
3. **MCP is a client, not a server** — MCP Streamable HTTP client code lives under `fabric/` or `runtime/`; the MCP server implementation remains in the MCP tool server repository.
4. **Specs before features** — implementation specs land in `docs/specs/` per AI-SDLC; features trace to their feature docs. PR gate: feature PRs require a linked spec in `docs/specs/` (review-enforced at merge time).

**Rejected alternatives:**

- **Runtime code inside a shared planning workspace** — Rejected: planning workspaces are doc-native; mixing runtime code breaks repo boundaries; CI/release cycles differ.
- **Multi-repo per domain agent** (research, finance) — Rejected: violates "same artifact, profile-driven placement" success criterion; duplicates CI, observability, and deployment pipelines; supervisor routing needs co-located agents.
- **Cloud SDK in business logic with "we'll abstract later"** — Rejected: PoC proved deferral creates permanent lock-in; D1 makes abstraction Phase 1, not Phase 3.
- **Separate repos for fabric vs runtime** — Rejected: Phase 1 ships federation skeleton + runtime in one deployable unit; split adds network/version coupling without independent release value.

## Consequences

### Becomes Easier

- One CI pipeline, one container image, one Helm chart — aligned with inherited MCP-server ADR-027.
- Unit tests mock Protocols without AWS credentials.
- New cloud targets add a `providers/<vendor>/` subtree without touching business logic.
- Clear onboarding: "business logic in `src/mira/` except `providers/`."

### Becomes Harder

- Import-linter maintenance as package tree grows — new top-level dirs need explicit allow/deny rules; mitigated by versioned import-linter contracts in-repo and review when adding packages (see ADR-004 CI scaffold).
- Contributors must understand the boundary — accidental SDK imports in `runtime/` fail CI until moved.
- Docs-and-code single-repo workflow requires discipline — ADR updates travel in dedicated `adr/` branches ([ADR-003](./adr-003-branching-strategy-and-repo-workflow.md)); code PRs reference ADR/issue IDs in the description rather than editing decision records.

## Applies To

- **MIRA-ARCH** — provider & middleware epic (primary owner of layout)
- **MIRA-PLACE** — repo bootstrap, CI scaffold, branch protection
- **MIRA-RUNTIME**, **MIRA-FABRIC**, **MIRA-MODEL** — all Phase 1 code lands in this structure
- **MIRA-CONNECTORS** — source connector adapters (Markdown docs connector, CSV ledger connector) land under `fabric/` and `runtime/` per layout
- [ADR-002](./adr-002-provider-abstraction-pattern.md) — Protocol interfaces and factory detail
- [ADR-003](./adr-003-branching-strategy-and-repo-workflow.md) — branching rules for this repo
- [ADR-004](./adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md) — CI compliance gates including import-boundary lint

## Links

- ADR file: `docs/adr/adr-001-repository-structure-and-provider-isolation-layout.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-001
- Architecture: `docs/architecture/` (agent architecture overview)
- Inherited: MCP-server ADR-026 (deployment target & IaC), MCP-server ADR-027 (one codebase, multiple deployment profiles)
