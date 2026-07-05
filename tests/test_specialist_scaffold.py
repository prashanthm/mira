"""Tests for the reusable specialist-subgraph scaffold."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mira.connectors import export_tools
from mira.connectors.docs import from_file
from mira.orchestration.reasoning import ReasoningBudget
from mira.orchestration.specialist_scaffold import (
    RegisteredTool,
    build_specialist_subgraph,
    filter_tools_by_domain,
)
from mira.orchestration.specialists.domains import FINANCE_DOMAIN, RESEARCH_DOMAIN
from mira.tools.contract import ToolContract

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


def _finance_stub_tool() -> RegisteredTool:
    contract = ToolContract(
        name="ledger.explore",
        description="Stub finance exploration tool",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
        required_entitlement="connector:ledger:explore",
    )

    def handler(_payload: dict) -> dict:
        return {"status": "explored"}

    return RegisteredTool(contract=contract, handler=handler)


def test_scaffold_instantiates_second_domain() -> None:
    tools = _docs_registered_tools() + [_finance_stub_tool()]
    research = build_specialist_subgraph(RESEARCH_DOMAIN, tools)
    finance = build_specialist_subgraph(FINANCE_DOMAIN, tools)

    assert research.domain_spec.domain_id == "research"
    assert finance.domain_spec.domain_id == "finance"
    assert research.reasoning_loop is not finance.reasoning_loop


def test_specialists_have_isolated_checkpoints() -> None:
    tools = _docs_registered_tools() + [_finance_stub_tool()]
    research = build_specialist_subgraph(RESEARCH_DOMAIN, tools)
    finance = build_specialist_subgraph(FINANCE_DOMAIN, tools)

    research_result = research.invoke("research-only query", thread_id="shared-thread")
    finance_result = finance.invoke("finance-only query", thread_id="shared-thread")

    assert research_result.query == "research-only query"
    assert finance_result.query == "finance-only query"

    research_again = research.invoke("research-only query", thread_id="shared-thread")
    finance_again = finance.invoke("finance-only query", thread_id="shared-thread")

    assert research_again.query == research_result.query
    assert finance_again.query == finance_result.query
    assert research_again.plan_steps
    assert finance_again.plan_steps


def test_research_rejects_out_of_domain_tool() -> None:
    tools = _docs_registered_tools() + [_finance_stub_tool()]
    research = build_specialist_subgraph(RESEARCH_DOMAIN, tools)
    filtered = filter_tools_by_domain(tools, RESEARCH_DOMAIN)
    assert all(tool.contract.name.startswith("docs.") for tool in filtered)

    loop = research.reasoning_loop
    with pytest.raises(PermissionError):
        loop._tool_fn("act:tool:ledger.explore:{}")


def test_filter_tools_by_domain_fail_closed_on_empty_allowlist() -> None:
    empty_domain = RESEARCH_DOMAIN.__class__(
        domain_id="empty",
        tool_prefixes=frozenset(),
    )
    assert filter_tools_by_domain(_docs_registered_tools(), empty_domain) == []

    specialist = build_specialist_subgraph(empty_domain, _docs_registered_tools())
    result = specialist.invoke("noop", thread_id="t1")
    assert result.error == "no tools allowed for domain"


def test_explicit_tool_channel_invokes_allowed_tool() -> None:
    tools = _docs_registered_tools()
    research = build_specialist_subgraph(RESEARCH_DOMAIN, tools, budget=ReasoningBudget(max_steps=5))
    loop = research.reasoning_loop

    observation = loop._tool_fn(
        'act:tool:docs.search:{"query":"middleware"}'
    )
    payload = json.loads(observation)
    assert payload["anchor"] == "middleware-ordering"
    assert payload["title"] == "Middleware Ordering"
