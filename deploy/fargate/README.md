# Fargate task definition (e05-f02-t01)

Profile-driven container packaging for the ECS/Fargate (`saas`) deployment path.

## Health checks

The container-level `healthCheck` is a **liveness** probe only. It uses the
image's own `python3` (stdlib `urllib`) rather than `curl`, because the slim
multi-stage build (ADR-026) is not guaranteed to ship `curl`. Any base image
swap must keep `python3` on `PATH`.

**Readiness** is intentionally not gated at the container level for the cloud
path. The ALB target group health check owns readiness on `/health/ready`
(mirroring the Helm chart's readiness probe in `values.yaml`), so a task is only
added to the load balancer once it reports ready. This keeps the Fargate task
definition's single liveness check consistent with the chart's two-probe
contract (`/health` liveness + `/health/ready` readiness).

## References

- Helm chart: `deploy/helm/mira/`
