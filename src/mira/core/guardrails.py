"""Bidirectional guardrail detectors and pipeline wiring (ADR-036/037/038).

Input side (guardrail_in stage, ADR-036): deterministic prompt-injection
pattern detection over the request query, and tool-abuse validation of proposed
tool calls against their ADR-031 typed contracts. Fail closed — an unknown
tool, out-of-contract arguments, or a destructive tool without an explicit
allow flag blocks the request before the handler runs.

Output side (guardrail_out stage, ADR-038): structural groundedness (claim →
source provenance attribution) and per-domain topic-drift checks over
dict-shaped results. Final results that fail groundedness are blocked; streamed
chunks are recorded, never broken mid-stream (mirrors the ADR-009
:class:`GuardrailOutMiddleware` exit discipline).

Detectors are deterministic and offline; model-graded detection layers plug in
behind the same detector/checker seams (ADR-037 secondary layer).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from mira.core.middleware import (
    GuardrailOutMiddleware,
    NextFn,
    Pipeline,
    RequestContext,
)
from mira.tools.contract import ToolContract, ToolValidationError, validate_input

QUERY_KEY = "query"
TOOL_CALLS_KEY = "tool_calls"
IN_FINDINGS_KEY = "guardrail_in_findings"
OUT_FINDINGS_KEY = "guardrail_out_findings"

# Finding codes (stable identifiers for telemetry / escalation / audit).
INJECTION_CODE = "prompt_injection"
UNKNOWN_TOOL_CODE = "unknown_tool"
ARGS_OUT_OF_CONTRACT_CODE = "args_out_of_contract"
DESTRUCTIVE_BLOCKED_CODE = "destructive_tool_blocked"
TOOL_REGISTRY_MISSING_CODE = "tool_registry_missing"
UNGROUNDED_CODE = "ungrounded_answer"
TOPIC_DRIFT_CODE = "topic_drift"


class GuardrailViolation(Exception):
    """A guardrail stage rejected the request/response (fail closed)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ViolationFinding:
    """One detector hit: stable code, the rule that matched, and the evidence."""

    code: str
    pattern: str
    snippet: str


# Deterministic instruction-override patterns (case-insensitive, whitespace
# tolerant). Each targets an *imperative* override shape, so ordinary text that
# merely mentions "instructions" or "prompt" does not match.
_DEFAULT_INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(your|the)\s+(system\s+)?prompt",
    r"you\s+are\s+now",
    r"reveal\s+(your|the)\s+(system\s+)?prompt",
    r"override\s+(your\s+)?(rules|instructions)",
    r"forget\s+(all\s+)?(previous|prior|above)\s+instructions",
)


class InjectionDetector:
    """Deterministic pattern detector for instruction-override attempts.

    ``extra_patterns`` is the config hook: deployments append tenant- or
    domain-specific patterns without subclassing.
    """

    def __init__(self, *, extra_patterns: Iterable[str] = ()) -> None:
        patterns = (*_DEFAULT_INJECTION_PATTERNS, *extra_patterns)
        self._compiled = tuple(re.compile(p, re.IGNORECASE) for p in patterns)

    def check(self, text: str) -> ViolationFinding | None:
        for regex in self._compiled:
            match = regex.search(text or "")
            if match is not None:
                return ViolationFinding(
                    code=INJECTION_CODE,
                    pattern=regex.pattern,
                    snippet=match.group(0),
                )
        return None


class ToolAbuseDetector:
    """Validates a proposed tool call against a registry of ADR-031 contracts.

    Fail closed: an unknown tool name, arguments that fail the contract's
    ``inputSchema``, or a ``destructiveHint`` tool without an explicit allow
    flag all produce a finding.
    """

    def __init__(
        self,
        contracts: Mapping[str, ToolContract] | Iterable[ToolContract],
        *,
        allow_destructive: bool = False,
    ) -> None:
        if isinstance(contracts, Mapping):
            self._contracts = dict(contracts)
        else:
            self._contracts = {contract.name: contract for contract in contracts}
        self._allow_destructive = allow_destructive

    def check(
        self,
        name: str,
        args: Mapping[str, Any] | None,
        *,
        allow_destructive: bool | None = None,
    ) -> ViolationFinding | None:
        contract = self._contracts.get(name)
        if contract is None:
            return ViolationFinding(
                code=UNKNOWN_TOOL_CODE,
                pattern="name in registry",
                snippet=f"tool {name!r} is not registered",
            )
        try:
            validate_input(contract, dict(args or {}))
        except ToolValidationError as exc:
            return ViolationFinding(
                code=ARGS_OUT_OF_CONTRACT_CODE,
                pattern="inputSchema",
                snippet=exc.message,
            )
        allowed = self._allow_destructive if allow_destructive is None else allow_destructive
        if contract.destructiveHint and not allowed:
            return ViolationFinding(
                code=DESTRUCTIVE_BLOCKED_CODE,
                pattern="destructiveHint requires explicit allow",
                snippet=f"tool {name!r} is destructive and not explicitly allowed",
            )
        return None


class TextDetector(Protocol):
    """Any detector with an ``InjectionDetector``-shaped ``check(text)``."""

    def check(self, text: str) -> ViolationFinding | None: ...


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


def _has_provenance(node: Any) -> bool:
    """Recursive ADR-045 grounding rule: a ``provenance`` mapping carrying
    ``source_type`` + ``source_id`` at the top level or on any nested mapping."""
    if not isinstance(node, Mapping) or not node:
        return False
    prov = node.get("provenance")
    if isinstance(prov, Mapping) and prov.get("source_type") and prov.get("source_id"):
        return True
    return any(
        isinstance(value, Mapping) and _has_provenance(value) for value in node.values()
    )


def _iter_source_types(node: Any) -> Iterable[str]:
    """Yield every provenance ``source_type`` found in a nested answer mapping."""
    if not isinstance(node, Mapping):
        return
    prov = node.get("provenance")
    if isinstance(prov, Mapping) and prov.get("source_type"):
        yield str(prov["source_type"])
    for value in node.values():
        if isinstance(value, Mapping):
            yield from _iter_source_types(value)


class GroundednessChecker:
    """Structural claim→source check over a SpecialistResult-shaped dict.

    An answer with content must carry provenance attribution (the recursive
    ADR-045 rule). Error results carry no claims, so they pass; a non-error
    result whose answer lacks provenance is ungrounded.
    """

    def check(self, result: Mapping[str, Any]) -> ViolationFinding | None:
        if "answer" not in result:
            return None  # not a specialist-result shape; nothing to assert
        if result.get("error"):
            return None  # error results assert no claims
        answer = result.get("answer") or {}
        if _has_provenance(answer):
            return None
        return ViolationFinding(
            code=UNGROUNDED_CODE,
            pattern="answer must carry provenance(source_type, source_id)",
            snippet=json.dumps(answer, default=str)[:200],
        )


class TopicDriftDetector:
    """Per-domain drift check: answer provenance must stay inside the routed
    domain's tool prefixes (ADR-038).

    Constructed from plain data (``domain_id -> tool prefixes``) so core never
    imports orchestration. A result whose answer provenance ``source_type``
    maps to a *different* domain's prefix is drift.
    """

    def __init__(self, domain_prefixes: Mapping[str, Iterable[str]]) -> None:
        self._domains: dict[str, frozenset[str]] = {
            domain: frozenset(prefix.rstrip(".") for prefix in prefixes)
            for domain, prefixes in domain_prefixes.items()
        }

    def _domain_for_source(self, source_type: str) -> str | None:
        for domain, roots in self._domains.items():
            if source_type in roots or any(
                source_type.startswith(f"{root}.") for root in roots
            ):
                return domain
        return None

    def check(self, result: Mapping[str, Any]) -> ViolationFinding | None:
        routed = result.get("domain")
        if not routed or routed not in self._domains:
            return None  # unrouted / unknown-domain results are not drift-scored
        for source_type in _iter_source_types(result.get("answer") or {}):
            owner = self._domain_for_source(source_type)
            if owner is not None and owner != routed:
                return ViolationFinding(
                    code=TOPIC_DRIFT_CODE,
                    pattern="answer provenance must match routed domain prefixes",
                    snippet=(
                        f"source_type {source_type!r} belongs to domain {owner!r}, "
                        f"result routed to {routed!r}"
                    ),
                )
        return None


class OutputChecker(Protocol):
    """Any output checker with a ``check(result_dict)`` shape."""

    def check(self, result: Mapping[str, Any]) -> ViolationFinding | None: ...


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
