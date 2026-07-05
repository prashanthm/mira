# ADR-047: Deployment Profiles & Packaging

## Status

Accepted

## Context

The initiative requires the **same artifact** on the hosted SaaS platform, standalone customer cloud, AWS Outposts, and customer Kubernetes — **profile-driven**, not fork-driven. This extends the platform pattern in the inherited MCP-server ADR-027 (one codebase, multiple deployment profiles) and the container/IaC baseline in MCP-server ADR-026 (deployment target and IaC).

[ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md) places Terraform under `infra/` and Helm under `deploy/helm/`. [ADR-002](./adr-002-provider-abstraction-pattern.md) resolves `PLATFORM` and provider backends per profile. This ADR names **Mira-specific profiles**, packaging paths, and profile-controlled dimensions.

> **Traceability note.** Inherited ADRs prefixed `MCP-server` live in the separate MCP tool server repository; they are cited here by number and title rather than linked, and resolve only against a checkout of that repository.
>
> Mira ADRs (`adr-001`, `adr-002`, `adr-033`, `adr-048`) and epics (`MIRA-PLACE`, `MIRA-ARCH`, `MIRA-MODEL`) are tracked in this repo under `docs/adr/`. The `MIRA-*` epic files are not yet committed; their `Applies To` links currently point at `product-brief.md` and will be repointed when those files land (tracked as a follow-up).

## Decision Drivers

1. **Initiative success criterion** — "Same artifact runs on the hosted SaaS platform, standalone, AWS Outposts, and customer Kubernetes (profile-driven)."
2. **Inherited MCP-server ADR-027** — deployment profile as configuration bundle; no code branching on profile name.
3. **Inherited MCP-server ADR-026** — Docker multi-stage, Terraform IaC, Bedrock AgentCore as supported target.
4. **MIRA-PLACE epic** — multi-placement deploy, Helm/operator path.
5. **Outposts constraints** — subset of AWS services; graceful degradation when Secrets Manager unavailable (inherited MCP-server ADR-027, outposts row).

## Decision

Ship **one container image** per release. Select behavior via **`DEPLOYMENT_PROFILE`** environment variable at container startup. Profile is resolved **once at startup**; changing profile requires restart (same rationale as the inherited MCP-server ADR-027 rejecting runtime profile switching).

**Profile definitions:**

| Profile | Target | `PLATFORM` | Secrets (ISecretsProvider) | Partition / tenant | Notes |
|---------|--------|------------|------------------------------|-------------------|-------|
| `local` | Developer laptop | `local` | env / dotenv | static dev tenant | `skip_auth=true` allowed; optional StdIO MCP for local tools |
| `standalone` | Customer VPC / dedicated | `aws` | env or SSM | static partition | Single-tenant; customer IdP |
| `saas` | Hosted multi-tenant SaaS | `aws` | AWS Secrets Manager | gateway-injected tenant | Production default for the hosted SaaS platform |
| `outposts` | AWS Outposts | `aws` | SSM (Secrets Manager if available) | static | Degraded AWS service set; feature flags off when service missing |
| `kubernetes` | Customer EKS / K8s | `aws` or `local` | customer choice | per deployment | Helm chart; probes per ADR-006 |

**Profile-controlled dimensions** (explicit env overrides always win over profile defaults):

| Dimension | Settings | Reference |
|-----------|----------|-----------|
| Provider platform | `PLATFORM` | ADR-002 |
| Auth bypass | `skip_auth` | ADR-033 (local only) |
| MCP endpoint | `MCP_BASE_URL` | the MCP tool server deployment |
| Bedrock / model region | `AWS_REGION`, model IDs | MIRA-MODEL |
| Feature flags | `ENABLE_*` | ADR-019 Phase 3 aggregation, ADR-028+ |
| Observability | `OTLP_ENDPOINT`, `LOG_LEVEL` | inherited MCP-server ADR-013 |

**Dimension rules:**

- **`skip_auth` is permitted only in the `local` profile.** When `skip_auth=true` is resolved under any non-`local` profile (`standalone`, `saas`, `outposts`, `kubernetes`), startup **fails fast** with a structured error and the process exits non-zero — it is never silently honored. This enforces the auth-side rule from ADR-033 (authentication and authorization model) at the deployment layer.
- **Feature flags are evaluated against service availability at startup.** For profiles that may run against a degraded AWS service set (notably `outposts`), each `ENABLE_*` flag whose dependency is unreachable is flipped **off** during the startup service-discovery probe, and the decision is recorded with a `feature_disabled_due_to_unavailable_service` structured log entry naming the flag and the missing dependency. Flags are not best-effort at request time — the resolved set is fixed once at startup, consistent with the resolve-once-at-startup model above.

**Packaging:**

1. **Docker** — multi-stage build, non-root user, read-only root FS where compatible; image scanned in CI (ADR-004).
2. **Terraform** — `infra/` modules per profile target (ECS Fargate, EKS add-ons); state backend pattern follows the existing artifact-registry-infra precedent when the Mira AWS account is provisioned.
3. **Helm** — `deploy/helm/mira` chart with values overlays: `values-saas.yaml`, `values-standalone.yaml`, `values-outposts.yaml`, `values-kubernetes.yaml`. Overlays are version-controlled in-chart (no out-of-band values) and validated in CI against the chart's `values.schema.json` plus a `helm template` + `helm lint` per overlay, so a missing or malformed key fails the build rather than the deploy.
4. **Bedrock AgentCore** — maintain `/invocations` compatibility (ADR-006); AgentCore deployment is one profile target, not a separate image.

**Startup logging:**

On successful resolution, emit one `profile_resolved` record naming the effective profile, platform, applied overrides, and key endpoints:

```json
{"event": "profile_resolved", "profile": "saas", "platform": "aws", "overrides": ["log_level"], "mcp_url": "https://..."}
```

Startup is **fail-fast on misconfiguration**, not best-effort:

- **Unknown profile** — an unrecognized `DEPLOYMENT_PROFILE` logs `{"event": "profile_resolution_failed", "reason": "unknown_profile", "value": "..."}` and exits non-zero.
- **Missing required env** — a required variable absent for the resolved profile (e.g. `MCP_BASE_URL` in a non-`local` profile) logs `{"event": "profile_resolution_failed", "reason": "missing_required_env", "var": "MCP_BASE_URL", "profile": "saas"}` and exits non-zero. Required-vs-optional is defined per profile; the process never starts on a default for a required value.
- **Optional env defaulted** — an absent optional variable that falls back to a default logs a warning `{"event": "profile_default_applied", "var": "LOG_LEVEL", "default": "info"}` and continues.
- **Disallowed override** — e.g. `skip_auth=true` outside `local`, logged per the §Dimension rules above and treated as fail-fast.
- **Unavailable dependency** — degraded-service flag flips are recorded via `feature_disabled_due_to_unavailable_service` (see §Dimension rules); these are warnings, not failures, for profiles where degradation is expected (`outposts`).

**Rejected alternatives:**

- **Separate images per target** — Rejected: inherited MCP-server ADR-027; duplicates CI scan/build; violates success criterion.
- **Git branches per environment** — Rejected: ADR-003; configuration not branches differentiate placement.
- **Runtime profile switching via admin API** — Rejected: same as the inherited MCP-server ADR-027 — auth mode and provider registration inconsistent mid-process.
- **Lambda-only serverless agent** — Rejected: inherited MCP-server ADR-026; warm runtime, streaming, and long MCP sessions ill-suited to Lambda timeouts.

**Security:**

Secrets are sourced **only** through the per-profile `ISecretsProvider` named in the profile table (env/dotenv for `local`, SSM/Secrets Manager for AWS profiles, customer choice for `kubernetes`) — never baked into the image and never logged. The `profile_resolved` record emits provider *names* and endpoint URLs, not values. Cross-profile rules:

- Image is identical across profiles (one digest); no profile carries embedded credentials, so a leaked image discloses no environment secrets.
- `saas` requires AWS Secrets Manager; falling back to plaintext env for this profile is a startup failure, not a silent downgrade.
- Network isolation, egress control, and runtime hardening for these profiles are owned by [ADR-048](./adr-048-secure-cloud-runtime-and-network-isolation.md) — this ADR commits the secrets-source-per-profile contract; ADR-048 commits the network/runtime boundary.

**Outposts service-availability probes:**

The `outposts` profile (and any profile that may run against a degraded AWS service set) runs **startup probes** before serving traffic. The probe rule, not its full implementation, is fixed here (implementation is owned by MIRA-PLACE):

- Each dependency a feature flag relies on (e.g. Secrets Manager, Bedrock region endpoint) is probed once at startup with a bounded timeout.
- An unreachable dependency flips its dependent `ENABLE_*` flag off and emits `feature_disabled_due_to_unavailable_service` (see §Dimension rules); it does **not** block startup for profiles where degradation is expected.
- A *required* dependency (one with no degraded-mode fallback for the resolved profile) that is unreachable is a fail-fast startup error, logged as `profile_resolution_failed` with `reason: required_dependency_unavailable`.
- Probe latency budget and retry/backoff are an implementation concern deferred to MIRA-PLACE; this ADR fixes the flag-flip-vs-fail-fast decision.

**Profile-matrix testing strategy:**

The "profile matrix must be tested in CI" consequence below is scoped here so the test shape is committed, with implementation owned by MIRA-PLACE:

- **Positive path** — each profile resolves to its expected `PLATFORM`, secrets provider, and required-env set; `helm template` + `helm lint` succeed for each overlay against `values.schema.json`.
- **Negative path** — unknown `DEPLOYMENT_PROFILE`, missing required env per profile, and `skip_auth=true` outside `local` each produce the expected `profile_resolution_failed` log and non-zero exit.
- **Degraded path** — for `outposts`, a simulated-unavailable dependency produces the expected `feature_disabled_due_to_unavailable_service` log and continued startup; a missing *required* dependency fails fast.
- **Smoke per profile** — container boot + `/invocations` (or `/healthz`) reachable per profile where an environment is feasible in CI.

## Consequences

### Becomes Easier

- One release pipeline tags `v*` on `main`; all customers receive same digest with different values files.
- New placement = new profile row + Helm values — no code fork.
- Operations read startup log for effective configuration.

### Becomes Harder

- Profile matrix must be tested in CI (smoke per profile where feasible).
- Adding a new settings dimension requires updating every profile default table.
- Outposts profile needs startup service-availability probes (latency + failure modes).

## Applies To

- **MIRA-PLACE** — primary epic
- **MIRA-ARCH** — provider factory defaults per profile
- **MIRA-MODEL** — regional Bedrock configuration
- All epics — feature flags may gate Phase 2/3 capabilities per profile
- [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md), [ADR-002](./adr-002-provider-abstraction-pattern.md), [ADR-048](./adr-048-secure-cloud-runtime-and-network-isolation.md)
- Inherited: MCP-server ADR-026 (deployment target and IaC), MCP-server ADR-027 (one codebase, multiple deployment profiles)

## Links

- ADR file: `docs/adr/adr-047-deployment-profiles-and-packaging.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-047
