"""Tests for contract validation middleware in the tool execution pipeline."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mira.core.middleware import Pipeline, RequestContext
from mira.core.tool_validation import TOOL_CONTRACT_KEY, TOOL_PAYLOAD_KEY, ToolValidationMiddleware
from mira.tools.contract import ToolContract, ToolValidationError, validate_input


def _flat_contract(**overrides: Any) -> ToolContract:
    defaults: dict[str, Any] = {
        "name": "get_well",
        "description": "Fetch well metadata by id",
        "inputSchema": {
            "type": "object",
            "properties": {
                "well_id": {"type": "string"},
                "include_logs": {"type": "boolean"},
            },
            "required": ["well_id"],
            "additionalProperties": False,
        },
        # ToolContract is fail-closed on entitlement (authz declaration, #21).
        "required_entitlement": "users.tools.invoke@partition.dataservices.energy",
    }
    defaults.update(overrides)
    return ToolContract(**defaults)


def test_valid_tool_call_passes_through_handler() -> None:
    contract = _flat_contract()
    pipeline = Pipeline({"guardrail_in": ToolValidationMiddleware()})
    ctx = RequestContext(
        attributes={
            TOOL_CONTRACT_KEY: contract,
            TOOL_PAYLOAD_KEY: {"well_id": "W-1"},
        }
    )
    handler_ran = False

    async def handler(_ctx: RequestContext) -> dict[str, str]:
        nonlocal handler_ran
        handler_ran = True
        return {"name": "Well W-1"}

    result = asyncio.run(pipeline.run(ctx, handler))

    assert handler_ran
    assert result == {"name": "Well W-1"}
    assert ctx.attributes["guardrail_out_exits"] == [{"name": "Well W-1"}]


def test_malformed_input_rejected_handler_not_invoked() -> None:
    contract = _flat_contract()
    pipeline = Pipeline({"guardrail_in": ToolValidationMiddleware()})
    ctx = RequestContext(
        attributes={
            TOOL_CONTRACT_KEY: contract,
            TOOL_PAYLOAD_KEY: {"include_logs": True},
        }
    )
    handler_ran = False

    async def handler(_ctx: RequestContext) -> str:
        nonlocal handler_ran
        handler_ran = True
        return "should not run"

    with pytest.raises(ToolValidationError) as exc_info:
        asyncio.run(pipeline.run(ctx, handler))

    assert not handler_ran
    assert "well_id" in exc_info.value.message or "required" in exc_info.value.message.lower()
    # guardrail_in (ToolValidation) rejects before reaching guardrail_out, so the
    # output guardrail must never have recorded an exit (L1: was a tautology).
    assert not ctx.attributes.get("guardrail_out_exits")


def test_non_dict_payload_rejected_before_handler() -> None:
    contract = _flat_contract()
    pipeline = Pipeline({"guardrail_in": ToolValidationMiddleware()})
    ctx = RequestContext(
        attributes={TOOL_CONTRACT_KEY: contract, TOOL_PAYLOAD_KEY: "not-a-dict"}
    )
    handler_ran = False

    async def handler(_ctx: RequestContext) -> str:
        nonlocal handler_ran
        handler_ran = True
        return "should not run"

    with pytest.raises(ToolValidationError, match="must be a dict"):
        asyncio.run(pipeline.run(ctx, handler))

    assert handler_ran is False
    assert not ctx.attributes.get("guardrail_out_exits")


def test_output_guardrail_invoked_on_success() -> None:
    contract = _flat_contract()
    pipeline = Pipeline({"guardrail_in": ToolValidationMiddleware()})
    ctx = RequestContext(
        attributes={
            TOOL_CONTRACT_KEY: contract,
            TOOL_PAYLOAD_KEY: {"well_id": "W-2"},
        }
    )

    async def handler(_ctx: RequestContext) -> dict[str, int]:
        return {"count": 3}

    asyncio.run(pipeline.run(ctx, handler))

    exits = ctx.attributes["guardrail_out_exits"]
    assert len(exits) == 1
    assert exits[0] == {"count": 3}


def test_skips_validation_when_no_contract_in_context() -> None:
    pipeline = Pipeline({"guardrail_in": ToolValidationMiddleware()})
    ctx = RequestContext()

    async def handler(_ctx: RequestContext) -> str:
        return "passthrough"

    assert asyncio.run(pipeline.run(ctx, handler)) == "passthrough"


def test_validate_input_directly_matches_contract_module() -> None:
    contract = _flat_contract()
    validate_input(contract, {"well_id": "W-1"})
    with pytest.raises(ToolValidationError):
        validate_input(contract, {})
