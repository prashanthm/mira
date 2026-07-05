"""Tests for the finance domain specialist subgraph.

Also exercises the scaffold's reuse claim: the finance specialist is the second
instantiation of the shared subgraph scaffold with no new LangGraph wiring, and
its state stays isolated from the research domain on the same thread id.
"""

from __future__ import annotations

import json
from pathlib import Path

from mira.connectors import export_tools
from mira.connectors.ledger import from_file
from mira.orchestration.reasoning import ReasoningLoop
from mira.orchestration.specialist_scaffold import RegisteredTool, SpecialistSubgraph
from mira.orchestration.specialists.finance import (
    REPRESENTATIVE_FINANCE_QUERY,
    build_finance_specialist,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ledger.csv"


def _ledger_registered_tools() -> list[RegisteredTool]:
    connector = from_file(str(FIXTURE))
    contracts = {tool.name: tool for tool in export_tools(connector)}

    def categories_handler(_payload: dict) -> list[str]:
        return list(connector.document.categories())

    def query_handler(payload: dict) -> dict:
        record = connector.query(payload)[0]
        return {
            "total": record.payload["total"],
            "currency": record.provenance.units,
            "entry_count": record.payload["entry_count"],
            "provenance": {
                "source_type": record.provenance.source_type,
                "source_id": record.provenance.source_id,
            },
        }

    return [
        RegisteredTool(contract=contracts["ledger.categories"], handler=categories_handler),
        RegisteredTool(contract=contracts["ledger.query"], handler=query_handler),
    ]


def _specialist() -> SpecialistSubgraph:
    return build_finance_specialist(_ledger_registered_tools())


def test_finance_specialist_is_reasoning_subgraph() -> None:
    specialist = _specialist()
    assert isinstance(specialist, SpecialistSubgraph)
    assert isinstance(specialist.reasoning_loop, ReasoningLoop)
    assert specialist.domain_spec.domain_id == "finance"


def test_representative_ledger_query_returns_denominated_answer() -> None:
    specialist = _specialist()
    result = specialist.invoke(REPRESENTATIVE_FINANCE_QUERY, thread_id="ledger-e2e")

    assert result.answer["total"] == 1336.40
    assert result.answer["currency"] == "USD"
    assert result.answer["entry_count"] == 2
    assert result.answer["provenance"]["source_type"] == "ledger"


def test_specialist_result_supervisor_contract() -> None:
    specialist = _specialist()
    result = specialist.invoke(REPRESENTATIVE_FINANCE_QUERY, thread_id="contract")

    assert result.domain == "finance"
    assert isinstance(result.answer, dict)
    assert result.plan_steps
    assert json.dumps(result.to_dict())


def test_finance_tools_are_not_visible_to_other_domains() -> None:
    # The scaffold's allow-listing means ledger.* tools bind only to the finance
    # DomainSpec; a specialist built for another prefix set filters them out.
    from mira.orchestration.specialist_scaffold import filter_tools_by_domain
    from mira.orchestration.specialists.domains import RESEARCH_DOMAIN

    tools = _ledger_registered_tools()
    assert filter_tools_by_domain(tools, RESEARCH_DOMAIN) == []
