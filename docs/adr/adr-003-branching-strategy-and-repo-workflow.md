# ADR-003: Branching Strategy & Repo Workflow

## Status

Accepted

## Context

The **`mira` code repository** ([ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md)) holds both runtime code and planning docs (ADRs, epics, features under `docs/`); it needs a branching model before Foundation CI scaffold and first product code.

Deployment placement differs by **environment configuration and profiles** ([ADR-047](./adr-047-deployment-profiles-and-packaging.md), inherited MCP-server ADR-027) — not by long-lived git branches per target. The AI-SDLC standard mandates PR-based delivery with measurable traceability (`closes #N` → Shipped).

Precedents: the MCP tool server's branching strategy and the AI-SDLC standard's feature-direct cycle.

## Decision Drivers

1. **foundation-readiness Tier 1** — branching strategy and PR rules must be recorded before first product code.
2. **Inherited MCP-server ADR-027** — "one artifact, many profiles"; git branches per deployment target create drift and cherry-pick burden.
3. **Feature-direct build cycle** — implement-from-feature skill expects `feature/<issue#>-<slug>` branches merging to `main` via reviewed PR.
4. **Compliance ([ADR-004](./adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md))** — branch protection requires PR-only merges to protected `main`.
5. **Docs + code coordination** — ADRs, epics, and code share one repository; the same branch naming convention covers doc changes and code changes for cognitive load.

## Decision

Adopt **trunk-based development** with **short-lived topic branches** and **PR-only merges** to `main` in `prashanthm/mira` — for runtime code and planning docs alike.

**Branch naming:**

```
<type>/<issue#>-<short-slug>
```

| Type | Use |
|------|-----|
| `feature` | Feature implementation, new capability |
| `fix` | Bug fix |
| `adr` | ADR drafts and updates (`docs/adr/`) |
| `docs` | Documentation-only (planning docs, specs) |
| `chore` | Tooling, CI, dependency updates |

Examples: `feature/117-fabric-skeleton`, `adr/118-tier1-repo-structure`, `docs/108-adr-catalog`.

Branch prefix `feature/` matches the AI-SDLC `implement-from-feature` skill and `feature-implement.prompt.md`; Conventional Commits `feat:` remains the commit-message type (workflow rule 4). Other repositories may use `feat/` as their precedent; Mira adopts `feature/` for agent-driven delivery.

**Workflow rules:**

1. **Default branch** — `main` is always releasable; protected with required reviews and status checks.
2. **No direct commits to `main`** — all changes via pull request.
3. **Branch lifetime** — days, not weeks; rebase or merge from `main` frequently.
4. **Commit messages** — reference GitHub issue: `feat(fabric): add MCP client skeleton (#117)`.
5. **PR body** — `Closes #N` when all acceptance criteria met; `Refs #N` for partial work.
6. **ADR PRs** — use the `adr/` branch type and touch only `docs/adr/`; code PRs reference ADR/issue IDs in the description rather than mixing ADR edits with feature code.
7. **Release tags** — semver git tags on `main` (`v0.1.0`) cut by release workflow; no `release/*` branches.
8. **No environment branches** — no `saas`, `outposts`, or `staging` long-lived branches; environment = deployment profile + infra workspace.

**Rejected alternatives:**

- **GitFlow (`develop` + release branches)** — Rejected: extra merge latency; release branches diverge from trunk; incompatible with continuous eval gates on `main`.
- **Long-lived branches per deployment target** — Rejected: explicit anti-pattern in inherited MCP-server ADR-027; duplicates Dockerfile/IaC maintenance without behavioral benefit.
- **Trunk-only (commit directly to `main`)** — Rejected: violates branch protection, commit-integrity conventions, and review gates in foundation-readiness.
- **Fork-per-customer** — Rejected: standalone customers receive profiles and configuration, not source forks.

## Consequences

### Becomes Easier

- One integration surface (`main`) for CI, eval gates, and container builds.
- Scorecard traceability: PR `closes #N` → feature Shipped.
- Same conventions across docs and code reduce onboarding friction.

### Becomes Harder

- Hotfix under pressure still requires a PR to protected `main` — no "quick commit" escape hatch.
- Features touching both an ADR and code need coordinated PRs referencing the same issue.

## Applies To

- **MIRA-PLACE** — CI/CD scaffold, branch protection setup
- **MIRA-EVAL** — eval CI gate runs on PRs to `main`
- All Phase 1 epics — implementation branches follow this convention
- [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md), [ADR-004](./adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md)
- AI-SDLC standard — feature-direct cycle

## Links

- ADR file: `docs/adr/adr-003-branching-strategy-and-repo-workflow.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-003
- Precedent: the MCP tool server's branching strategy
