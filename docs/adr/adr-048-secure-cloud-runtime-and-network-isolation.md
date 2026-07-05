# ADR-048: Secure Cloud Runtime & Network Isolation

## Status

Accepted

## Context

The predecessor PoC evaluation flagged **PUBLIC network mode** and missing VPC isolation as **P0 enterprise blockers**. The predecessor hardening spec **D6 (infra-hardening)** mandates **VPC PRIVATE** deployment, WAF ingress, restricted egress, and VPC endpoints for AWS service calls.

This ADR applies to **AWS-hosted profiles** (`saas`, `standalone` on AWS, `outposts`, `kubernetes` on EKS). It complements [ADR-047](./adr-047-deployment-profiles-and-packaging.md) (Deployment Profiles & Packaging — **Accepted**) packaging with **network and runtime hardening** — not application auth (ADR-033) or client boundaries (ADR-005).

The inherited MCP-server ADR-026 (deployment target and IaC) establishes the Docker + Terraform baseline; the Mira agent runtime adds Bedrock, MCP client egress, and IdP JWKS fetch to the allow list.

## Decision Drivers

1. **Hardening spec D6** — PRIVATE VPC, interface endpoints, security group allow lists, WAF on ALB.
2. **PoC gap** — PUBLIC network mode failed security review.
3. **Regulated enterprise customers** — data residency and egress control expectations (Outposts variant in initiative charter).
4. **Bedrock + MCP architecture** — runtime must reach Bedrock, MCP server, OIDC JWKS, and configured source endpoints — not open internet.
5. **ADR-004** — container non-root, image scanning; network isolation completes defense in depth.

## Decision

Deploy AWS-hosted agent runtime in **VPC PRIVATE mode** with **defense-in-depth network controls**.

**Network topology (per deployment stack in `infra/`):**

```
Internet → WAF → ALB (TLS 1.2+) → Target Group (agent tasks/pods)
                                      ↓
                              Private subnets only
                              (no public IPs on tasks)
```

**1. Ingress**

- **AWS WAF** on Application Load Balancer — OWASP managed rule set + rate-based rules.
- **TLS termination** at ALB; HSTS enabled for SaaS profiles.
- **Security group (ingress)** — ALB → agent port only (e.g. 8080); deny direct internet to task ENIs.

**2. Egress (default deny, allow-list)**

- **VPC interface endpoints** (where available): `bedrock-runtime`, `logs`, `xray`, `ssm`, `secretsmanager` (profile-dependent), `ecr.api`, `ecr.dkr`, `sts`.
- **S3 gateway endpoint** for artifact/object access via `IObjectStore`.
- **Security group (egress)** — explicit allow to:
  - MCP tool server endpoint (the MCP tool server deployment URL)
  - OIDC IdP JWKS URL (HTTPS 443)
  - Customer-configured source endpoints. Each connector under MIRA-CONNECTORS lists its required outbound destinations in its feature spec, and that per-connector destinations table is the **source of truth** for the deployment SG egress rules — so egress rules cannot drift as connectors are added. (Phase 1+ ships a minimal set; "Phase 1+" = MVP launch onward, per the Mira roadmap phasing in the **product brief**.)
  - Deny `0.0.0.0/0` except via NAT **only when** a required external endpoint has no PrivateLink alternative.

**Egress exception documentation process:** every NAT/`0.0.0.0/0` exception and every non-PrivateLink external dependency is recorded as a comment block in the corresponding profile's `infra/` Terraform module README using a fixed template — fields: `destination`, `port/protocol`, `justification`, `privatelink_alternative_evaluated` (yes/no + why), `owner`, `review_date`. This keeps exception documentation consistent and auditable rather than ad hoc.

**3. Runtime hardening**

- **ECS Fargate or EKS** — private subnets; `awsvpc` / pod security standards.
- **Container:** non-root user, drop Linux capabilities, read-only root filesystem where compatible (writable `/tmp` only).
- **Secrets:** never in image layers; inject via `ISecretsProvider` / task IAM role (ADR-002, inherited MCP-server ADR-006).
- **Task IAM role (least privilege):** the task role is scoped to the minimum required actions, resource-constrained to this deployment's ARNs — `secretsmanager:GetSecretValue` / `ssm:GetParameter` on the deployment's secret/parameter paths only, `bedrock:InvokeModel*` on the allow-listed model ARNs, `logs:PutLogEvents` + `xray:PutTraceSegments` for the observability path, and `s3:GetObject`/`PutObject` on the configured `IObjectStore` bucket prefix. No wildcard (`*`) resources and no broad `iam:`/admin actions. Exact policy lives in the `infra/` Terraform module per profile.
- **IMDSv2** required on EC2-backed nodes (if any); Fargate uses task role only.

**4. Outposts profile (`outposts`)**

- Same PRIVATE principle; endpoints limited to services available on Outpost.
- Startup probe detects missing endpoints (e.g. Secrets Manager) → fall back to SSM Parameter Store via the `ISecretsProvider` SSM implementation per the ADR-047 profile table (pending — see [adr-list.md](adr-list.md)); the fallback is a read-path swap only and preserves the same task-IAM least-privilege boundary (see §3).
- **`degraded_mode` observability:** the probe emits a structured log line `degraded_mode=true` with the missing-endpoint name to CloudWatch Logs via the OTLP path in §5; deployment specs SHOULD configure a CloudWatch metric filter + alarm on this field so degraded startups page operators rather than failing silently.

**5. Observability**

- OTLP to AWS X-Ray / CloudWatch via VPC endpoint (inherited MCP-server ADR-013, metrics and tracing).
- VPC Flow Logs enabled on agent subnets — **90-day default retention** (regulated baseline, matches the inherited MCP-server pattern) with per-customer-compliance-profile override.

**6. mTLS**

- **Not** application-layer mTLS for user JWT clients (rejected in the inherited MCP-server ADR-005 for SaaS UX).
- **Optional** service mesh mTLS (EKS) for agent↔MCP **when both run in same mesh** — documented in deployment spec, not Phase 1 requirement.

**Rejected alternatives:**

- **PUBLIC subnet tasks with security group only** — Rejected: PoC P0 finding; fails hardening spec D6 and enterprise review.
- **Open egress (`0.0.0.0/0`)** — Rejected: exfiltration risk; incompatible with regulated customer expectations.
- **Application-layer mTLS replacing JWT** — Rejected: inherited auth model; heavy for multi-tenant SaaS browser clients.
- **Bare EC2 + systemd without orchestrator** — Rejected: inherited MCP-server ADR-026; loses health probes, rolling deploy, and pod/task isolation.

## Consequences

### Becomes Easier

- Security review checklist maps to Terraform modules (WAF, endpoints, SG rules).
- Consistent with the MCP tool server's hardened deployment patterns.
- Outposts customers get same isolation model with documented degradation.

### Becomes Harder

- Every new external dependency requires egress rule + exception documentation.
- VPC endpoint cost and quota management per account/region.
- Local dev (`local` profile) does not replicate full network stack. **Mitigation:** network-isolation behavior (egress allow-list, endpoint reachability, `degraded_mode` fallback) is validated in a dedicated ephemeral test VPC stood up from the same `infra/` Terraform modules and exercised in CI on a pre-deploy gate, not in `local`; `local` uses mocked AWS endpoints (e.g. LocalStack) for fast iteration but is explicitly **not** the network-control verification environment.

## Applies To

- **MIRA-PLACE** — primary implementation epic
- **MIRA-MODEL** — Bedrock via VPC endpoint
- **MIRA-OBS** — OTLP egress path
- [ADR-047](./adr-047-deployment-profiles-and-packaging.md) (Deployment Profiles & Packaging — **Accepted**) — profile-specific Terraform/Helm
- [ADR-004](./adr-004-compliance-conformance-license-signed-commits-and-dependency-scanning.md) (Compliance Conformance — **Accepted**) — container hardening
- Inherited: MCP-server ADR-026 (deployment target and IaC)

## Links

- ADR file: `docs/adr/adr-048-secure-cloud-runtime-and-network-isolation.md`
- Catalog: [adr-list.md](adr-list.md) — ADR-048
