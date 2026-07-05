# ADR-044: Incident Detection & Remediation Workflow

Status: Proposed

## Context

Production incidents in an agent platform have shapes traditional alerting misses: a prompt
rollout that degrades answer quality without raising error rates, a specialist stuck in expensive
retrieval loops that burns cost budget before any latency alarm fires, a provider brownout that
silently shifts traffic down the ADR-011 fallback chain, or a guardrail regression that ADR-045
would have caught in CI but appeared only under production traffic. Mira needs an
anomaly-triggered detection and escalation workflow designed for these failure modes.

Detection is the first open question: which anomalies are computed over the ADR-042 telemetry
(cost signatures, fallback-activation spikes, guardrail-block-rate shifts, SLO burn-rate alerts
from ADR-043), what the baseline/thresholding approach is, and how alert fatigue is controlled in
a system whose per-request behavior is legitimately variable. Escalation is the second: routing to
on-call with runbooks, severity classification, and how an incident's blast radius is described in
agent terms (which tenants, agents, prompt versions).

Remediation is where the agent platform differs most: the platform already has levers that can be
thrown without a code deploy — the ADR-012 kill switch to roll back a prompt/tool version, ADR-011
routing overrides to pin or exclude a provider, and per-agent disable via the supervisor roster.
The open sub-question is which remediations may fire automatically on high-confidence detections
versus requiring a human decision, and how every automated action is itself audited.

## Decision (pending)

This ADR will select the anomaly-detection rules, the escalation/on-call workflow, and the
remediation lever policy (automatic vs. human-approved) for production AgentOps. It builds on
ADR-042's telemetry and anomaly signals and ADR-043's error-budget burn alerts as triggers, and
on the ADR-012 kill switch and ADR-011 routing controls as the code-deploy-free remediation
levers; escalation delivery reuses the notification mechanism selected in ADR-039.

Planned phase: E (AgentOps, with ADR-042 and ADR-043).
