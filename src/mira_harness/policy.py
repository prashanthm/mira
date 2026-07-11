"""Policy-plane detectors: injection, tool abuse, groundedness, drift (ADR-036/037/038).

Extracted from ``mira.core.guardrails`` (ADR-050): these are the deterministic,
offline, agent-agnostic *detectors*; the middleware stages that wire them into
Mira's request pipeline stay in ``mira.core.guardrails`` (Mira's transport) and
re-export these names.

Detectors operate on plain text and on the shared result mapping shape — the
``SpecialistResult.to_dict()`` fields, byte-compatible with the public
``TraceResult`` contract (ADR-049) — so they front foreign agents unchanged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from mira_contracts.tooling import ToolContract, ToolValidationError, validate_input

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

    Constructed from plain data (``domain_id -> tool prefixes``) so the policy
    plane never imports orchestration. A result whose answer provenance
    ``source_type`` maps to a *different* domain's prefix is drift.
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


__all__ = [
    "ARGS_OUT_OF_CONTRACT_CODE",
    "DESTRUCTIVE_BLOCKED_CODE",
    "INJECTION_CODE",
    "TOOL_REGISTRY_MISSING_CODE",
    "TOPIC_DRIFT_CODE",
    "UNGROUNDED_CODE",
    "UNKNOWN_TOOL_CODE",
    "GroundednessChecker",
    "GuardrailViolation",
    "InjectionDetector",
    "OutputChecker",
    "TextDetector",
    "ToolAbuseDetector",
    "TopicDriftDetector",
    "ViolationFinding",
]
