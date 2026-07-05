"""Markdown document-corpus connector — the research demo source (ADR-019, ADR-020).

An anti-corruption adapter (ADR-020) that parses a Markdown document — YAML-style
front-matter headers + ``##`` sections → headers + titled sections — into the uniform
connector shape (:class:`SourceRecord` carrying :class:`Provenance` with a section
anchor), publishes typed MCP tools, and grounds an attributed query-in-place answer
through the fabric (ADR-019). Dependency-free by design: a vendor SDK would violate
the no-SDK-in-the-business-layer rule (ADR-002). Source data is untrusted; provenance
(source + section anchor) travels with every record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mira.connectors.base import Provenance, SourceDescription, SourceRecord
from mira.connectors.mcp_export import ToolSpec

_CAP_SECTIONS = "sections"
_CAP_SEARCH = "search"


class DocsParseError(ValueError):
    """Raised when a Markdown document is malformed (unterminated front-matter, no sections)."""


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")


@dataclass(frozen=True, slots=True)
class DocSection:
    """One ``##`` section: anchor slug, title, and its body text."""

    anchor: str
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class DocsDocument:
    """Parsed Markdown file: front-matter headers + ordered ``##`` sections."""

    headers: dict[str, str]
    sections: tuple[DocSection, ...]

    def section(self, anchor: str) -> DocSection:
        """Return the section with *anchor* (case-insensitive)."""
        target = anchor.strip().lower()
        for section in self.sections:
            if section.anchor == target:
                return section
        raise DocsParseError(
            f"no section {anchor!r} (known: {', '.join(s.anchor for s in self.sections)})"
        )

    def search(self, term: str) -> tuple[DocSection, ...]:
        """Return sections whose title or body contains *term* (case-insensitive)."""
        needle = term.strip().lower()
        if not needle:
            return ()
        return tuple(
            s for s in self.sections
            if needle in s.title.lower() or needle in s.body.lower()
        )


def parse_markdown(text: str) -> DocsDocument:
    """Parse Markdown *text* (front-matter + ``##`` sections) into a :class:`DocsDocument`.

    Front-matter is an optional leading ``---`` block of ``key: value`` lines. Content
    before the first ``##`` heading is skipped. Raises :class:`DocsParseError` on an
    unterminated front-matter block or a document with no ``##`` sections.
    """
    headers: dict[str, str] = {}
    lines = text.splitlines()
    idx = 0

    if lines and lines[0].strip() == "---":
        idx = 1
        closed = False
        while idx < len(lines):
            line = lines[idx].strip()
            idx += 1
            if line == "---":
                closed = True
                break
            if line and ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip()] = value.strip()
        if not closed:
            raise DocsParseError("unterminated front-matter block (missing closing '---')")

    sections: list[DocSection] = []
    title: str | None = None
    body_lines: list[str] = []

    def _flush() -> None:
        if title is not None:
            sections.append(
                DocSection(anchor=_slugify(title), title=title, body="\n".join(body_lines).strip())
            )

    for raw in lines[idx:]:
        heading = re.match(r"^##\s+(.*)$", raw)
        if heading:
            _flush()
            title = heading.group(1).strip()
            body_lines = []
        elif title is not None:
            body_lines.append(raw)
    _flush()

    if not sections:
        raise DocsParseError("Markdown document has no '##' sections")
    return DocsDocument(headers=headers, sections=tuple(sections))


@dataclass(slots=True)
class DocsConnector:
    """Markdown adapter for :class:`~mira.connectors.base.SourceConnector`.

    Parses one Markdown document up front and serves uniform records. Also satisfies
    the federation dispatch protocol (``connector_id`` / ``source_name``) so the same
    instance grounds a query-in-place answer (ADR-019).
    """

    SOURCE_TYPE: str = field(default="docs", init=False)
    document: DocsDocument
    source_id: str

    @property
    def connector_id(self) -> str:
        """Stable connector identity for federation attribution."""
        return f"docs:{self.source_id}"

    @property
    def source_name(self) -> str:
        """Source identity for federation attribution."""
        return self.source_id

    def describe(self) -> SourceDescription:
        """Advertise the docs source type and its read capabilities."""
        return SourceDescription(
            source_type=self.SOURCE_TYPE, capabilities=(_CAP_SECTIONS, _CAP_SEARCH)
        )

    def tool_specs(self) -> list[ToolSpec]:
        """Declare read-only, entitlement-bearing MCP tools for the docs ops (ADR-031)."""
        return [
            ToolSpec(
                capability=_CAP_SECTIONS,
                required_entitlement="connector:docs:sections",
                description="List the section anchors and titles in the document corpus",
            ),
            ToolSpec(
                capability=_CAP_SEARCH,
                required_entitlement="connector:docs:search",
                description="Search document sections by keyword, returning attributed snippets",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
        ]

    def query(self, request: Any) -> list[SourceRecord]:
        """Search sections by keyword, returning uniform attributed records.

        Accepts a mapping or a :class:`~mira.fabric.federation.QueryRequest` carrying
        ``{"query": <term>}``; provenance carries the section anchor so grounding
        attributes a citable location, not bare prose.
        """
        payload = getattr(request, "payload", request)
        if not isinstance(payload, dict):
            raise DocsParseError(f"docs query payload must be a mapping, got {type(payload)!r}")
        term = payload.get("query")
        if term is None:
            raise DocsParseError("docs query requires 'query'")

        matches = self.document.search(str(term))
        if not matches:
            raise DocsParseError(f"no sections match {term!r}")

        return [
            SourceRecord(
                provenance=Provenance(
                    source_type=self.SOURCE_TYPE,
                    source_id=f"{self.source_id}#{section.anchor}",
                ),
                payload={
                    "anchor": section.anchor,
                    "title": section.title,
                    "snippet": section.body[:280],
                    "doc_title": self.document.headers.get("title"),
                },
            )
            for section in matches
        ]


def from_text(text: str, *, source_id: str) -> DocsConnector:
    """Build a :class:`DocsConnector` from Markdown *text* attributed to *source_id*."""
    return DocsConnector(document=parse_markdown(text), source_id=source_id)


def from_file(path: str) -> DocsConnector:
    """Build a :class:`DocsConnector` from a Markdown file, attributed to its path."""
    with open(path, encoding="utf-8") as handle:
        return from_text(handle.read(), source_id=path)
