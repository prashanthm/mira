# ADR-004: Compliance Conformance — License, Signed Commits & Dependency Scanning

## Status

Accepted

## Context

Mira adopts established **delivery-gate conventions** — license policy, commit integrity, and dependency scanning enforced in CI — rather than inventing a parallel compliance framework. This ADR records **how the `mira` repository conforms**, for both code PRs and planning-doc (ADR/epic) PRs.

The hardening spec set targets **SOC 2**, **EU AI Act** (transparency / Limited Risk posture for agent UX), and **NIST AI RMF**. Foundation does not implement every control — it **blocks first product code** until license policy, commit integrity, and dependency scanning are enforced in CI.

The predecessor PoC evaluation flagged missing eval framework, weak auth, and PUBLIC network mode as enterprise blockers — compliance gates prevent repeating those gaps at greenfield.

## Decision Drivers

1. **Delivery-gate conventions** — local conformance recorded here; no re-decision of the inherited gate definitions.
2. **foundation-readiness** — license policy ADR accepted, commit-integrity convention documented, dependency scanning enabled before first code line.
3. **Regulated adopters** — enterprise operators expect audit trails, SBOM, and traceable releases (research L01 governance emphasis).
4. **Single protected trunk** — all changes merge via protected `main` ([ADR-003](./adr-003-branching-strategy-and-repo-workflow.md)).
5. **Precedent** — the inherited MCP-server ADRs: OIDC-only CI cloud auth, container scanning.

## Decision

Adopt the following **compliance baseline** for the `mira` repository, enforced at CI and branch protection.

**1. License policy**

- **Default license:** Apache-2.0 for `mira` application code, recorded in a `LICENSE` file at the repo root (aligned with common open-source norms unless legal direction says otherwise).
- **Third-party licenses:** CI job runs `pip-licenses` or equivalent; **fail on copyleft contamination** in dependency closure unless explicitly allowlisted in `docs/compliance/license-allowlist.md`.
- **ADR acceptance:** this ADR satisfies the foundation-readiness "License policy ADR accepted" gate; legal review gate before first public release tag.

**2. Signed commits**

- **Convention:** commit signing (GPG or SSH) is **recommended but optional** for the reference repository; the convention is documented in CONTRIBUTING.md.
- **Enterprise posture:** deployments of Mira in regulated environments can enable required signature verification on `main` via branch protection alone — no code or workflow change is needed; the branching model ([ADR-003](./adr-003-branching-strategy-and-repo-workflow.md)) already assumes PR-only merges.
- **Bot commits** (dependabot, github-actions) are handled via a bot allowlist documented in CONTRIBUTING.md when signature enforcement is enabled.

**3. Dependency scanning**

- **Python:** `pip-audit` (or OSV scanner) on every PR touching `pyproject.toml` / lockfile, plus **Dependabot** alerts and update PRs enabled on the repo; blocking on Critical/High CVEs without documented exception.
- **Container:** Trivy or registry-native scan on built image in CI before push (inherits the MCP-server container-scanning pattern).
- **Infrastructure:** `tfsec` or `checkov` on `infra/` Terraform in PR plan workflow.

**4. SBOM & traceability (pre-ship, not Foundation-blocking)**

- Container build emits SPDX/CycloneDX SBOM artifact stored with release tag.
- PR template includes an AI attribution table per the delivery-gate conventions; copied into the repo at MIRA-PLACE bootstrap.

**CI cloud auth:** follows an OIDC-only pattern — no long-lived cloud keys in CI (deployment wiring in MIRA-PLACE).

**5. EU AI Act / NIST (Phase 1 posture)**

- Foundation records **intent** to meet transparency and risk-management practices via decision traces (ADR-040, Phase 3), eval CI gate ([ADR-045](./adr-045-eval-framework-ci-safety-gate.md)), and human oversight (ADR-039) — not a separate compliance stack in Phase 1.

**Rejected alternatives:**

- **Defer all compliance to Phase 3 (MIRA-SAFETY / MIRA-EVAL)** — Rejected: foundation-readiness explicitly blocks first code without license, commit-integrity, and scanning gates.
- **Custom one-off compliance framework** — Rejected: duplicates established delivery-gate conventions for no benefit; the catalog inherits them by design.
- **Compliance as markdown-only** — Rejected: PoC failures (no eval, no JWT verify) showed policy without CI enforcement is ineffective.
- **Mandatory signed commits for all contributors** — Rejected for the reference repository: raises contribution friction without changing the security model of a reference implementation; regulated deployments get equivalent enforcement by flipping branch protection, which this ADR explicitly preserves as a supported posture.

## Consequences

### Becomes Easier

- Foundation review checklist has explicit ADR to cite.
- Security reviewers find gates in one place (CONTRIBUTING + CI workflows).
- Consistent posture with the inherited MCP-server conventions.

### Becomes Harder

- CVE exceptions require documented allowlist maintenance.
- License allowlist reviews needed when adding dependencies with non-Apache licenses.
- Enterprise adopters enabling signature enforcement must configure signing before first merge.

## Applies To

- **MIRA-PLACE** — CI workflow implementation
- **MIRA-EVAL** — eval gate complements dependency scanning (different concern)
- All Phase 1 epics — code merges subject to these gates
- [ADR-001](./adr-001-repository-structure-and-provider-isolation-layout.md), [ADR-003](./adr-003-branching-strategy-and-repo-workflow.md)
- Inherited: delivery-gate compliance checklist (foundation-readiness)

## Links

- ADR file: `docs/adr/adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-004
- Hardening spec set: production-hardening proposal
