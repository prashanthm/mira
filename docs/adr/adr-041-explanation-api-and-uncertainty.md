# ADR-041: Explanation API & Uncertainty Quantification

Status: Proposed

## Context

ADR-006 reserved an `/explain` convention in the agent-facing API standard: for any completed
request, a client can ask *why* — which sources were consulted, which reasoning path was taken,
and how confident the system is in each claim. The audience is layered: an end user wants a
one-paragraph justification with citations; a reviewer wants the claim-by-claim evidence table; an
auditor wants the full decision trace. The open question is the design of that API and of the
uncertainty signals it exposes.

For explanations, the current thinking is multi-level views projected from the ADR-040 decision
trace — summary, claim-level, and full-trace — rather than a separately generated post-hoc
narrative, so explanations cannot diverge from what actually happened. Open sub-questions include
whether summaries are pre-generated at answer time or on-demand, how entitlements bound what a
given caller may see of a trace, and versioning of explanation views as the trace schema evolves.

For uncertainty quantification, the honest options are limited and the ADR must be explicit about
what the numbers mean: candidates include retrieval-support scores (from ADR-028/029 critique
verdicts), model-derived confidence (calibration required), claim-level agreement across
self-consistency samples, and simple categorical bands (supported / partially supported /
unsupported) derived from ADR-038 faithfulness checks. Exposing a poorly calibrated probability
is worse than a coarse but truthful band.

## Decision (pending)

This ADR will select the `/explain` API design (resource shape, levels, authorization) and the
uncertainty-quantification model surfaced alongside answers. It builds on the ADR-040 append-only
attribution store as the system of record explanations are projected from, the ADR-006 API
conventions for the endpoint itself, and the ADR-038 check verdicts and retrieval-critique scores
(ADR-029) as uncertainty inputs.

Planned phase: D (safety & trust, with ADR-036, ADR-038, ADR-039, ADR-040).
