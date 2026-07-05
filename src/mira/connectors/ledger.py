"""CSV ledger connector — the finance demo source (ADR-019, ADR-020).

An anti-corruption adapter (ADR-020) that parses a CSV transaction ledger —
``date,account,category,amount,currency`` rows → typed entries — into the uniform
connector shape (:class:`SourceRecord` carrying :class:`Provenance` with the
currency as its unit), publishes typed MCP tools, and grounds an attributed
query-in-place answer through the fabric (ADR-019). Dependency-free by design: a
vendor SDK would violate the no-SDK-in-the-business-layer rule (ADR-002). Source
data is untrusted; provenance (source + currency unit) travels with every record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mira.connectors.base import Provenance, SourceDescription, SourceRecord
from mira.connectors.mcp_export import ToolSpec

_CAP_CATEGORIES = "categories"
_CAP_QUERY = "query"

_EXPECTED_HEADER = ("date", "account", "category", "amount", "currency")


class LedgerParseError(ValueError):
    """Raised when a ledger CSV is malformed (bad header, ragged row, non-numeric amount)."""


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One transaction: ISO date, account, category, signed amount, currency."""

    date: str
    account: str
    category: str
    amount: float
    currency: str


@dataclass(frozen=True, slots=True)
class LedgerDocument:
    """Parsed ledger: ordered transaction entries."""

    entries: tuple[LedgerEntry, ...]

    def categories(self) -> tuple[str, ...]:
        """Return the distinct categories in sorted order."""
        return tuple(sorted({e.category for e in self.entries}))

    def total(self, category: str, period: str) -> tuple[float, str, int]:
        """Sum *category* amounts for dates starting with *period* (e.g. ``"2026-03"``).

        Returns ``(total, currency, entry_count)``. Raises :class:`LedgerParseError`
        if no entries match or the matched entries mix currencies (a silent mixed-
        currency sum would be a wrong answer — ADR-023's normalization concern).
        """
        matched = [
            e for e in self.entries
            if e.category.lower() == category.strip().lower() and e.date.startswith(period)
        ]
        if not matched:
            raise LedgerParseError(f"no entries for category {category!r} in period {period!r}")
        currencies = {e.currency for e in matched}
        if len(currencies) > 1:
            raise LedgerParseError(
                f"mixed currencies {sorted(currencies)} for {category!r} in {period!r}; "
                "normalize before aggregating"
            )
        return sum(e.amount for e in matched), matched[0].currency, len(matched)


def parse_ledger(text: str) -> LedgerDocument:
    """Parse CSV *text* (``date,account,category,amount,currency``) into a :class:`LedgerDocument`.

    Blank lines and ``#`` comment lines are skipped. Raises :class:`LedgerParseError`
    on a missing/wrong header, a ragged row, or a non-numeric amount.
    """
    rows = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not rows:
        raise LedgerParseError("ledger CSV is empty")

    header = tuple(col.strip().lower() for col in rows[0].split(","))
    if header != _EXPECTED_HEADER:
        raise LedgerParseError(
            f"ledger header must be {','.join(_EXPECTED_HEADER)!r}, got {rows[0]!r}"
        )

    entries: list[LedgerEntry] = []
    for row in rows[1:]:
        cols = [col.strip() for col in row.split(",")]
        if len(cols) != len(_EXPECTED_HEADER):
            raise LedgerParseError(
                f"ragged ledger row: expected {len(_EXPECTED_HEADER)} cols, got {len(cols)}"
            )
        date, account, category, amount_raw, currency = cols
        try:
            amount = float(amount_raw)
        except ValueError as exc:
            raise LedgerParseError(f"non-numeric amount: {row!r}") from exc
        entries.append(
            LedgerEntry(
                date=date, account=account, category=category, amount=amount, currency=currency
            )
        )

    if not entries:
        raise LedgerParseError("ledger CSV has a header but no entries")
    return LedgerDocument(entries=tuple(entries))


@dataclass(slots=True)
class LedgerConnector:
    """Ledger adapter for :class:`~mira.connectors.base.SourceConnector`.

    Parses one ledger CSV up front and serves uniform records. Also satisfies the
    federation dispatch protocol (``connector_id`` / ``source_name``) so the same
    instance grounds a query-in-place answer (ADR-019).
    """

    SOURCE_TYPE: str = field(default="ledger", init=False)
    document: LedgerDocument
    source_id: str

    @property
    def connector_id(self) -> str:
        """Stable connector identity for federation attribution."""
        return f"ledger:{self.source_id}"

    @property
    def source_name(self) -> str:
        """Source identity for federation attribution."""
        return self.source_id

    def describe(self) -> SourceDescription:
        """Advertise the ledger source type and its read capabilities."""
        return SourceDescription(
            source_type=self.SOURCE_TYPE, capabilities=(_CAP_CATEGORIES, _CAP_QUERY)
        )

    def tool_specs(self) -> list[ToolSpec]:
        """Declare read-only, entitlement-bearing MCP tools for the ledger ops (ADR-031)."""
        return [
            ToolSpec(
                capability=_CAP_CATEGORIES,
                required_entitlement="connector:ledger:categories",
                description="List the distinct spend categories in the ledger",
            ),
            ToolSpec(
                capability=_CAP_QUERY,
                required_entitlement="connector:ledger:query",
                description="Total a category's spend for a period (e.g. '2026-03')",
                input_schema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "period": {"type": "string"},
                    },
                    "required": ["category", "period"],
                    "additionalProperties": False,
                },
            ),
        ]

    def query(self, request: Any) -> list[SourceRecord]:
        """Total one category for a period, returning a uniform attributed record.

        Accepts a mapping or a :class:`~mira.fabric.federation.QueryRequest` carrying
        ``{"category": <name>, "period": <date prefix>}``; provenance carries the
        currency as its unit so grounding attributes a denominated amount, not a
        bare number.
        """
        payload = getattr(request, "payload", request)
        if not isinstance(payload, dict):
            raise LedgerParseError(
                f"ledger query payload must be a mapping, got {type(payload)!r}"
            )
        category, period = payload.get("category"), payload.get("period")
        if category is None or period is None:
            raise LedgerParseError("ledger query requires 'category' and 'period'")

        total, currency, count = self.document.total(str(category), str(period))
        return [
            SourceRecord(
                provenance=Provenance(
                    source_type=self.SOURCE_TYPE,
                    source_id=self.source_id,
                    units=currency,
                ),
                payload={
                    "category": str(category),
                    "period": str(period),
                    "total": round(total, 2),
                    "currency": currency,
                    "entry_count": count,
                },
            )
        ]


def from_text(text: str, *, source_id: str) -> LedgerConnector:
    """Build a :class:`LedgerConnector` from CSV *text* attributed to *source_id*."""
    return LedgerConnector(document=parse_ledger(text), source_id=source_id)


def from_file(path: str) -> LedgerConnector:
    """Build a :class:`LedgerConnector` from a CSV file, attributed to its path."""
    with open(path, encoding="utf-8") as handle:
        return from_text(handle.read(), source_id=path)
