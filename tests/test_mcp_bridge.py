"""Tests for the MCP→specialist bridge (fake tool objects, no network)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from mira.orchestration.mcp_bridge import (
    BridgedToolError,
    domain_spec_for_server,
    registered_tools_from_mcp,
)
from mira.orchestration.specialist_scaffold import build_specialist_subgraph

_FLAT_SCHEMA = {
    "type": "object",
    "properties": {"account": {"type": "string"}},
    "required": ["account"],
}

_DEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "filters": {
            "type": "object",
            "properties": {
                "range": {
                    "type": "object",
                    "properties": {"from": {"type": "string"}},
                }
            },
        }
    },
}


@dataclass
class _FakeTool:
    """Shape-compatible stand-in for a langchain-adapter MCP tool."""

    name: str
    description: str = "a fake MCP tool"
    args_schema: Any = None
    metadata: Any = None
    result: Any = '{"status": "ok"}'
    error: Exception | None = None
    calls: list[Any] = field(default_factory=list)

    def invoke(self, payload: Any) -> Any:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.result


class _SchemaModel:
    """Pydantic-style schema carrier (only the method the bridge uses)."""

    @staticmethod
    def model_json_schema() -> dict[str, Any]:
        return dict(_FLAT_SCHEMA)


def _bridge_one(tool: _FakeTool, **kwargs: Any):
    (registered,) = registered_tools_from_mcp([tool], **kwargs)
    return registered


# ── contract conversion ──────────────────────────────────────────────────────


def test_contract_carries_flat_schema_and_prefixed_entitlement() -> None:
    registered = _bridge_one(_FakeTool(name="vantage.positions", args_schema=dict(_FLAT_SCHEMA)))
    contract = registered.contract
    assert contract.name == "vantage.positions"
    assert contract.inputSchema == _FLAT_SCHEMA
    assert contract.required_entitlement == "mcp:vantage.positions"
    assert contract.readOnlyHint is True  # conservative default: presumed read-only


def test_entitlement_prefix_is_configurable() -> None:
    registered = _bridge_one(
        _FakeTool(name="vantage.positions"), entitlement_prefix="remote"
    )
    assert registered.contract.required_entitlement == "remote:vantage.positions"


def test_pydantic_style_schema_is_converted() -> None:
    registered = _bridge_one(_FakeTool(name="vantage.positions", args_schema=_SchemaModel))
    assert registered.contract.inputSchema == _FLAT_SCHEMA


def test_deep_schema_falls_back_to_permissive_object() -> None:
    registered = _bridge_one(_FakeTool(name="vantage.positions", args_schema=_DEEP_SCHEMA))
    assert registered.contract.inputSchema == {"type": "object", "additionalProperties": True}


def test_missing_schema_falls_back_to_permissive_object() -> None:
    registered = _bridge_one(_FakeTool(name="vantage.positions"))
    assert registered.contract.inputSchema == {"type": "object", "additionalProperties": True}


def test_read_only_hint_from_annotations_wins_over_default() -> None:
    registered = _bridge_one(
        _FakeTool(
            name="vantage.orders.place",
            metadata={"annotations": {"readOnlyHint": False}},
        )
    )
    assert registered.contract.readOnlyHint is False


# ── handler round-trip ───────────────────────────────────────────────────────


def test_handler_invokes_tool_and_parses_json_string_result() -> None:
    tool = _FakeTool(name="vantage.positions", result='{"total": 3, "unit": "shares"}')
    registered = _bridge_one(tool)
    assert registered.handler({"account": "a1"}) == {"total": 3, "unit": "shares"}
    assert tool.calls == [{"account": "a1"}]


def test_handler_wraps_non_dict_results() -> None:
    assert _bridge_one(_FakeTool(name="t.a", result="[1, 2]")).handler({}) == {"result": [1, 2]}
    assert _bridge_one(_FakeTool(name="t.b", result="plain text")).handler({}) == {
        "result": "plain text"
    }
    assert _bridge_one(_FakeTool(name="t.c", result=7)).handler({}) == {"result": 7}


def test_handler_passes_dict_results_through() -> None:
    registered = _bridge_one(_FakeTool(name="t.d", result={"already": "structured"}))
    assert registered.handler({}) == {"already": "structured"}


def test_remote_failure_raises_bridged_tool_error() -> None:
    tool = _FakeTool(name="vantage.positions", error=ConnectionError("server gone"))
    registered = _bridge_one(tool)
    with pytest.raises(BridgedToolError, match="vantage.positions.*server gone"):
        registered.handler({})


# ── domain spec derivation ───────────────────────────────────────────────────


def test_domain_spec_uses_server_namespace_prefix() -> None:
    tools = [_FakeTool(name="vantage.positions"), _FakeTool(name="vantage.balance")]
    spec = domain_spec_for_server("vantage", tools)
    assert spec.domain_id == "vantage"
    assert spec.tool_prefixes == frozenset({"vantage."})


def test_domain_spec_falls_back_to_observed_prefixes() -> None:
    tools = [_FakeTool(name="quotes.latest"), _FakeTool(name="ping")]
    spec = domain_spec_for_server("vantage", tools)
    assert spec.domain_id == "vantage"
    assert spec.tool_prefixes == frozenset({"quotes.", "ping"})


def test_domain_spec_without_tools_keeps_canonical_prefix() -> None:
    spec = domain_spec_for_server("vantage", [])
    assert spec.tool_prefixes == frozenset({"vantage."})


# ── end-to-end through the specialist scaffold ───────────────────────────────


def _specialist(*tools: _FakeTool):
    registered = registered_tools_from_mcp(list(tools))
    spec = domain_spec_for_server("vantage", [t for t in tools if t.name.startswith("vantage.")])
    return build_specialist_subgraph(spec, registered)


def test_bridged_tool_dispatches_through_explicit_tool_channel() -> None:
    tool = _FakeTool(name="vantage.positions", result='{"total": 3}')
    specialist = _specialist(tool)

    result = specialist.invoke(
        'check :tool:vantage.positions:{"account": "a1"}', thread_id="t1"
    )

    assert result.error is None
    assert result.answer == {"total": 3}
    assert tool.calls == [{"account": "a1"}]


def test_out_of_domain_tool_is_denied_fail_closed() -> None:
    inside = _FakeTool(name="vantage.positions")
    outside = _FakeTool(name="orders.place")
    specialist = _specialist(inside, outside)  # only the vantage.* surface is allow-listed
    # The bridged outside tool exists but was filtered out by the domain prefix.
    assert specialist.invoke(":tool:orders.place:", thread_id="t2").error
    assert outside.calls == []


def test_remote_failure_degrades_to_structured_tool_error_observation() -> None:
    tool = _FakeTool(name="vantage.positions", error=TimeoutError("deadline"))
    specialist = _specialist(tool)

    result = specialist.invoke(":tool:vantage.positions:", thread_id="t3")

    # Fail-degraded: the graph completes and the failure is a structured answer,
    # not an exception escaping the reasoning loop.
    assert result.answer["status"] == "tool_error"
    assert result.answer["tool"] == "vantage.positions"
    assert "deadline" in result.answer["detail"]
    assert json.dumps(result.to_dict())  # stays supervisor-serializable
