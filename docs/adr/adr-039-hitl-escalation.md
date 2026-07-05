# ADR-039: Human-in-the-Loop Escalation

Status: Proposed

## Context

Some agent actions are too consequential to execute autonomously: tool calls annotated
`destructive` in their ADR-031 typed contracts, actions that exceed a cost or scope threshold,
and outputs that fail ADR-038 controls but may still be salvageable with human judgment. Mira's
reasoning loop already has the primitive for this — ADR-013 adopted `interrupt()` HITL gates, and
durable execution means a paused run survives until a human responds without holding compute.

The open questions are policy and mechanism. Policy: which actions require escalation (annotation-
driven, risk-score-driven, or per-tenant configurable), who is authorized to approve, and what the
timeout behavior is (deny-by-default on expiry vs. queue indefinitely). Mechanism: the current
direction is an async webhook callback at the request boundary — the paused run emits an
escalation event to ticketing/chat tooling via the ADR-006 webhook conventions, and the approval
(or rejection) resumes the durable run with the decision recorded. Alternatives include a
synchronous approval UI in the Agent Chat surface and a polling inbox model; hybrids are likely
since interactive sessions and long-running background workflows have different latency
tolerances.

Every escalation is itself audit-relevant: the request, the evidence shown to the approver, the
decision, and the approver identity must land in the decision-trace record (ADR-040), and
approvals must not widen the task-scoped token (ADR-034) beyond what the approved action needs.

## Decision (pending)

This ADR will select the escalation policy model and the callback mechanism for human approval of
high-risk actions. It builds on `orchestration/interrupts.py` — the interrupt/resume seam the
ADR-013 loop already exposes — and on the guardrail_in / guardrail_out middleware stages (ADR-009)
as the points where a failed or flagged check converts into an interrupt rather than a hard
failure. The webhook contract follows the ADR-006 agent-facing API conventions.

Planned phase: D (safety & trust, with ADR-036, ADR-038, ADR-040, ADR-041).
