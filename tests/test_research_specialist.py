"""Tests for the research domain specialist subgraph."""

from __future__ import annotations

import json
from pathlib import Path

from mira.connectors import export_tools
from mira.connectors.docs import from_file
from mira.orchestration.reasoning import ReasoningLoop
from mira.orchestration.specialist_scaffold import RegisteredTool, SpecialistSubgraph
from mira.orchestration.specialists.research import (
    REPRESENTATIVE_RESEARCH_QUERY,
    build_research_specialist,
)

FIXTURE = Path(__file__).parent / "fixtures" / "handbook.md"


def _docs_registered_tools() -> list[RegisteredTool]:
    connector = from_file(str(FIXTURE))
    contracts = {tool.name: tool for tool in export_tools(connector)}

    def sections_handler(_payload: dict) -> list[dict[str, str]]:
        return [
            {"anchor": section.anchor, "title": section.title}
            for section in connector.document.sections
        ]

    def search_handler(payload: dict) -> dict:
        record = connector.query(payload)[0]
        return {
            "anchor": record.payload["anchor"],
            "title": record.payload["title"],
            "snippet": record.payload["snippet"],
            "provenance": {
                "source_type": record.provenance.source_type,
                "source_id": record.provenance.source_id,
            },
        }

    return [
        RegisteredTool(contract=contracts["docs.sections"], handler=sections_handler),
        RegisteredTool(contract=contracts["docs.search"], handler=search_handler),
    ]


def _specialist() -> SpecialistSubgraph:
    return build_research_specialist(_docs_registered_tools())


def test_research_specialist_is_reasoning_subgraph() -> None:
    specialist = _specialist()
    assert isinstance(specialist, SpecialistSubgraph)
    assert isinstance(specialist.reasoning_loop, ReasoningLoop)
    assert specialist.domain_spec.domain_id == "research"


def test_representative_docs_query_returns_attributed_answer() -> None:
    specialist = _specialist()
    result = specialist.invoke(REPRESENTATIVE_RESEARCH_QUERY, thread_id="docs-e2e")

    assert result.answer["anchor"] == "middleware-ordering"
    assert result.answer["title"] == "Middleware Ordering"
    assert "guardrail-in" in result.answer["snippet"]
    assert result.answer["provenance"]["source_type"] == "docs"


def test_specialist_result_supervisor_contract() -> None:
    specialist = _specialist()
    result = specialist.invoke(REPRESENTATIVE_RESEARCH_QUERY, thread_id="contract")

    assert result.domain == "research"
    assert isinstance(result.answer, dict)
    assert result.plan_steps
    assert json.dumps(result.to_dict())
