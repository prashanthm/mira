# Secure runtime Terraform (ADR-048)

IaC for the Mira agent runtime: private VPC, WAF-protected ALB ingress, restricted egress
(allow-list + VPC endpoints), least-privilege ECS task IAM, and a hardened Fargate container
definition.

## Topology

```
Internet → WAF → ALB (public subnets) → ECS tasks (private subnets, no public IP)
```

Private tasks reach AWS services via interface/gateway VPC endpoints. External dependencies
(MCP server, IdP JWKS, connector endpoints) are passed via `allowed_egress_cidrs`.

## Egress exception template

Record every NAT or non-PrivateLink destination in this README using the rows
below. The MCP/JWKS rows are Phase-1 templates (replace `TBD` CIDRs with real
destinations and set them in `allowed_egress_cidrs` before production apply):

| destination | port/protocol | justification | privatelink_alternative_evaluated | owner | review_date |
|-------------|---------------|---------------|-----------------------------------|-------|-------------|
| MCP server endpoint (TBD CIDR) | 443/tcp | Agent → MCP tool server; no PrivateLink offering | yes — none available | platform | TBD |
| IdP JWKS endpoint (TBD CIDR)   | 443/tcp | JWKS fetch for JWT validation at startup | yes — external IdP | platform | TBD |
| VPC DNS resolver (`var.vpc_cidr` base+2) | 53/udp+tcp | AmazonProvidedDNS for private endpoint resolution | n/a — in-VPC | platform | — |

## Base image contract

The container health check invokes the image's own `python3` (3.12+) rather than
`curl`, since hardened minimal images often omit `curl` and the root filesystem
is read-only. Any replacement base image MUST provide `python3` on `PATH`.

## Deferred / follow-up

- **HSTS on the ALB HTTPS listener (ADR-048 §1):** deferred to a profile-specific
  follow-up. ALB response-header injection (`strict-transport-security`) is a
  listener attribute not yet exposed as a first-class field across the pinned
  `aws` provider range; wire it (or a header-rewrite rule) for SaaS profiles when
  the profile wiring lands. Tracked against #57 follow-up.
- **`terraform validate` CI gate (AC-3 is `fmt -check` only):** deferred — the CI
  workflow lives outside this module's four-file scope (the PR was intentionally
  narrowed to Terraform). Add `terraform -chdir=deploy/terraform init -backend=false
  && terraform validate` (with a literal `certificate_arn`) in the CI-wiring task.

## Usage

```bash
terraform -chdir=deploy/terraform init
terraform -chdir=deploy/terraform plan -var certificate_arn=arn:aws:acm:...
```

Full `terraform plan`/apply against a live account is CI/human-tier verification.

## References

- [ADR-048](../../docs/adr/adr-048-secure-cloud-runtime-and-network-isolation.md)
