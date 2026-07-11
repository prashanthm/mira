"""Bidirectional guardrail pipeline wiring (ADR-036/037/038).

The deterministic *detectors* (injection, tool abuse, groundedness, topic
drift) moved to :mod:`mira_harness.policy` (ADR-050) and are re-exported here
for compatibility. This module keeps the Mira-transport halves: the ADR-009
middleware stages that run the detectors around a handler, and the guarded
pipeline builder.

Input side (guardrail_in stage, ADR-036): text detection over the request
query and tool-abuse validation of proposed tool calls. Fail closed — any
finding blocks the request before the handler runs.

Output side (guardrail_out stage, ADR-038): groundedness and per-domain
topic-drift checks over dict-shaped results. Final results that fail
groundedness are blocked; streamed chunks are recorded, never broken
mid-stream (mirrors the ADR-009 :class:`GuardrailOutMiddleware` exit
discipline).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from mira_harness.policy import (
    ARGS_OUT_OF_CONTRACT_CODE,
    DESTRUCTIVE_BLOCKED_CODE,
    INJECTION_CODE,
    TOOL_REGISTRY_MISSING_CODE,
    TOPIC_DRIFT_CODE,
    UNGROUNDED_CODE,
    UNKNOWN_TOOL_CODE,
    GroundednessChecker,
    GuardrailViolation,
    InjectionDetector,
    OutputChecker,
    TextDetector,
    ToolAbuseDetector,
    TopicDriftDetector,
    ViolationFinding,
)

from mira.core.middleware import (
    GuardrailOutMiddleware,
    NextFn,
    Pipeline,
    RequestContext,
)
from mira.tools.contract import ToolContract

QUERY_KEY = "query"
TOOL_CALLS_KEY = "tool_calls"
IN_FINDINGS_KEY = "guardrail_in_findings"
OUT_FINDINGS_KEY = "guardrail_out_findings"


class GuardrailInMiddleware:
    """guardrail_in stage: run input detectors before the handler (ADR-036/037).

    Reads ``ctx.attributes["query"]`` for text detection and the optional
    ``ctx.attributes["tool_calls"]`` list of ``{"name", "args"}`` mappings for
    tool-abuse detection. Findings are recorded in
    ``ctx.attributes["guardrail_in_findings"]`` and any finding raises
    :class:`GuardrailViolation` — the handler never runs.

    Fail-closed defaults: the injection detector is on unless explicitly
    replaced, and tool calls presented without a configured
    :class:`ToolAbuseDetector` are rejected (no registry means no basis to
    trust the call).
    """

    def __init__(
        self,
        *,
        detectors: Sequence[TextDetector] | None = None,
        tool_detector: ToolAbuseDetector | None = None,
    ) -> None:
        self._detectors: tuple[TextDetector, ...] = (
            tuple(detectors) if detectors is not None else (InjectionDetector(),)
        )
        self._tool_detector = tool_detector

    async def __call__(self, ctx: RequestContext, call_next: NextFn) -> Any:
        findings = self._collect_findings(ctx)
        recorded = ctx.attributes.setdefault(IN_FINDINGS_KEY, [])
        recorded.extend(findings)
        if findings:
            first = findings[0]
            raise GuardrailViolation(first.code, first.snippet)
        return await call_next()

    def _collect_findings(self, ctx: RequestContext) -> list[ViolationFinding]:
        findings: list[ViolationFinding] = []
        query = ctx.attributes.get(QUERY_KEY)
        if isinstance(query, str) and query:
            for detector in self._detectors:
                finding = detector.check(query)
                if finding is not None:
                    findings.append(finding)

        tool_calls = ctx.attributes.get(TOOL_CALLS_KEY) or []
        if tool_calls and self._tool_detector is None:
            findings.append(
                ViolationFinding(
                    code=TOOL_REGISTRY_MISSING_CODE,
                    pattern="tool_calls require a configured ToolAbuseDetector",
                    snippet=f"{len(tool_calls)} tool call(s) with no contract registry",
                )
            )
            return findings
        for call in tool_calls:
            finding = self._tool_detector.check(  # type: ignore[union-attr]
                str(call.get("name", "")),
                call.get("args"),
                allow_destructive=call.get("allow_destructive"),
            )
            if finding is not None:
                findings.append(finding)
        return findings


class CheckedGuardrailOutMiddleware(GuardrailOutMiddleware):
    """guardrail_out stage with output checkers (ADR-037/038).

    Every exit still flows through the parent's ``_on_exit`` discipline; on top
    of that, dict-shaped payloads are run through the output checkers and
    findings appended to ``ctx.attributes["guardrail_out_findings"]``. A
    groundedness violation on a FINAL (non-stream-chunk) result raises
    :class:`GuardrailViolation`; streamed chunks are recorded only — the stream
    is never broken mid-flight.
    """

    def __init__(self, *, checkers: Sequence[OutputChecker] | None = None) -> None:
        self._checkers: tuple[OutputChecker, ...] = (
            tuple(checkers) if checkers is not None else (GroundednessChecker(),)
        )

    def _findings_for(self, payload: Any) -> tuple[ViolationFinding, ...]:
        if not isinstance(payload, Mapping):
            return ()
        return tuple(
            finding
            for checker in self._checkers
            if (finding := checker.check(payload)) is not None
        )

    async def _on_exit(self, ctx: RequestContext, payload: Any) -> None:
        await super()._on_exit(ctx, payload)
        findings = self._findings_for(payload)
        if findings:
            ctx.attributes.setdefault(OUT_FINDINGS_KEY, []).extend(findings)

    async def _wrap_result(self, ctx: RequestContext, result: Any) -> Any:
        wrapped = await super()._wrap_result(ctx, result)
        if hasattr(wrapped, "__aiter__"):
            return wrapped  # per-chunk findings recorded in _on_exit, never raised
        blocking = [f for f in self._findings_for(result) if f.code == UNGROUNDED_CODE]
        if blocking:
            raise GuardrailViolation(blocking[0].code, blocking[0].snippet)
        return wrapped


def build_guarded_pipeline(
    *,
    contracts: Mapping[str, ToolContract] | Iterable[ToolContract] | None = None,
    domain_prefixes: Mapping[str, Iterable[str]] | None = None,
    extra_in: Sequence[TextDetector] = (),
    extra_out: Sequence[OutputChecker] = (),
    allow_destructive: bool = False,
) -> Pipeline:
    """ADR-009 pipeline with guardrail_in/guardrail_out stages wired (ADR-037).

    The injection detector and groundedness checker are always on (fail-closed
    primary layer); the tool-abuse detector and topic-drift detector activate
    when ``contracts`` / ``domain_prefixes`` are supplied.
    """
    detectors: list[TextDetector] = [InjectionDetector(), *extra_in]
    tool_detector = (
        ToolAbuseDetector(contracts, allow_destructive=allow_destructive)
        if contracts is not None
        else None
    )
    checkers: list[OutputChecker] = [GroundednessChecker()]
    if domain_prefixes is not None:
        checkers.append(TopicDriftDetector(domain_prefixes))
    checkers.extend(extra_out)
    return Pipeline(
        {
            "guardrail_in": GuardrailInMiddleware(
                detectors=detectors, tool_detector=tool_detector
            ),
            "guardrail_out": CheckedGuardrailOutMiddleware(checkers=checkers),
        }
    )


__all__ = [
    "ARGS_OUT_OF_CONTRACT_CODE",
    "DESTRUCTIVE_BLOCKED_CODE",
    "INJECTION_CODE",
    "IN_FINDINGS_KEY",
    "OUT_FINDINGS_KEY",
    "TOOL_REGISTRY_MISSING_CODE",
    "TOPIC_DRIFT_CODE",
    "UNGROUNDED_CODE",
    "UNKNOWN_TOOL_CODE",
    "CheckedGuardrailOutMiddleware",
    "GroundednessChecker",
    "GuardrailInMiddleware",
    "GuardrailViolation",
    "InjectionDetector",
    "ToolAbuseDetector",
    "TopicDriftDetector",
    "ViolationFinding",
    "build_guarded_pipeline",
]
