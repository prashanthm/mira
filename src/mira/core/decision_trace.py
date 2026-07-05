"""Append-only decision-trace audit store (ADR-040) and uncertainty summary (ADR-041).

Every request's claims, their source attributions, the plan steps taken, and
any guardrail findings land in an immutable :class:`TraceRecord`, correlated by
the inherited correlation ID (ADR-033) so it joins with the OTel trace. The
store is append-only by construction: records are frozen, sequence numbers are
assigned monotonically, and there is no update or delete surface.

The clock is injected at store construction — no wall-clock default is baked
in at import time. :func:`uncertainty_for` derives a deterministic structural
uncertainty summary from a record (no model call), served by the ``/explain``
endpoint (ADR-041).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

ClockFn = Callable[[], float]


@dataclass(frozen=True, slots=True)
class TracedClaim:
    """One claim from an answer with its claim→source attribution edge.

    ``statement`` is a deterministic repr of the claimed content; empty
    ``source_id``/``source_type`` mark a claim that carried no provenance.
    """

    statement: str
    source_id: str = ""
    source_type: str = ""

    @property
    def grounded(self) -> bool:
        return bool(self.source_id and self.source_type)

    def to_dict(self) -> dict[str, str]:
        return {
            "statement": self.statement,
            "source_id": self.source_id,
            "source_type": self.source_type,
        }


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """Immutable audit record for one request (ADR-040)."""

    trace_id: str
    correlation_id: str
    query: str
    claims: tuple[TracedClaim, ...]
    plan_steps: tuple[Mapping[str, Any], ...]
    guardrail_findings: tuple[Any, ...]
    sequence: int
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "query": self.query,
            "claims": [claim.to_dict() for claim in self.claims],
            "plan_steps": [dict(step) for step in self.plan_steps],
            "guardrail_findings": [_finding_to_dict(f) for f in self.guardrail_findings],
            "sequence": self.sequence,
            "created_at": self.created_at,
        }


def _finding_to_dict(finding: Any) -> Any:
    if isinstance(finding, Mapping):
        return dict(finding)
    if hasattr(finding, "code"):
        return {
            "code": getattr(finding, "code", ""),
            "pattern": getattr(finding, "pattern", ""),
            "snippet": getattr(finding, "snippet", ""),
        }
    return str(finding)


def _extract_claims(answer: Any) -> tuple[TracedClaim, ...]:
    """Claims from an answer mapping: one per provenance-carrying node.

    A non-empty answer that yields no provenance-carrying nodes produces a
    single ungrounded claim, so missing attribution stays visible in the audit
    record instead of vanishing.
    """
    claims = tuple(_walk_claims(answer))
    if not claims and isinstance(answer, Mapping) and answer:
        return (TracedClaim(statement=_statement_for(answer)),)
    return claims


def _walk_claims(node: Any) -> Iterable[TracedClaim]:
    if not isinstance(node, Mapping):
        return
    prov = node.get("provenance")
    if isinstance(prov, Mapping) and prov.get("source_type") and prov.get("source_id"):
        yield TracedClaim(
            statement=_statement_for(node),
            source_id=str(prov["source_id"]),
            source_type=str(prov["source_type"]),
        )
    for value in node.values():
        if isinstance(value, Mapping):
            yield from _walk_claims(value)


def _statement_for(node: Mapping[str, Any]) -> str:
    content = {
        key: value
        for key, value in node.items()
        if key != "provenance" and not isinstance(value, Mapping)
    }
    return json.dumps(content, sort_keys=True, default=str)


class TraceStore:
    """Append-only in-memory trace store (ADR-040).

    No update or delete methods exist; the internal list is never mutated
    after append and records themselves are frozen. Read surfaces return
    tuples so callers cannot mutate store state. Persistent backends slot in
    behind the same append/get/for_correlation contract (ADR-002/021 seams).
    """

    def __init__(self, *, clock: ClockFn) -> None:
        self._clock = clock
        self._records: list[TraceRecord] = []

    def append(
        self,
        *,
        trace_id: str,
        correlation_id: str,
        query: str,
        claims: Iterable[TracedClaim] = (),
        plan_steps: Iterable[Mapping[str, Any]] = (),
        guardrail_findings: Iterable[Any] = (),
    ) -> TraceRecord:
        record = TraceRecord(
            trace_id=trace_id,
            correlation_id=correlation_id,
            query=query,
            claims=tuple(claims),
            plan_steps=tuple(dict(step) for step in plan_steps),
            guardrail_findings=tuple(guardrail_findings),
            sequence=len(self._records),
            created_at=self._clock(),
        )
        self._records.append(record)
        return record

    def record_from_result(
        self,
        trace_id: str,
        correlation_id: str,
        result_dict: Mapping[str, Any],
        *,
        guardrail_findings: Iterable[Any] = (),
    ) -> TraceRecord:
        """Append a record extracted from a SpecialistResult-shaped dict.

        Claims are extracted from ``answer`` (provenance-carrying nodes become
        claim→source edges); ``plan_steps`` carry over verbatim.
        """
        return self.append(
            trace_id=trace_id,
            correlation_id=correlation_id,
            query=str(result_dict.get("query", "")),
            claims=_extract_claims(result_dict.get("answer") or {}),
            plan_steps=result_dict.get("plan_steps") or (),
            guardrail_findings=guardrail_findings,
        )

    def get(self, trace_id: str) -> TraceRecord | None:
        for record in self._records:
            if record.trace_id == trace_id:
                return record
        return None

    def for_correlation(self, correlation_id: str) -> tuple[TraceRecord, ...]:
        return tuple(
            record
            for record in self._records
            if record.correlation_id == correlation_id
        )

    def all(self) -> tuple[TraceRecord, ...]:
        return tuple(self._records)


def uncertainty_for(record: TraceRecord) -> dict[str, Any]:
    """Deterministic structural uncertainty summary for a trace record (ADR-041).

    No model call: the numbers are claim→source coverage plus flags. ``band``
    is a coarse categorical (supported / partially_supported / unsupported) —
    honest about what a structural check can and cannot assert.
    """
    total = len(record.claims)
    grounded = sum(1 for claim in record.claims if claim.grounded)
    ratio = (grounded / total) if total else 0.0
    missing_provenance = total == 0 or grounded < total
    if total and grounded == total:
        band = "supported"
    elif grounded:
        band = "partially_supported"
    else:
        band = "unsupported"
    return {
        "grounded_claims": grounded,
        "total_claims": total,
        "grounded_ratio": ratio,
        "has_guardrail_findings": bool(record.guardrail_findings),
        "missing_provenance": missing_provenance,
        "band": band,
    }


__all__ = [
    "ClockFn",
    "TraceRecord",
    "TraceStore",
    "TracedClaim",
    "uncertainty_for",
]
