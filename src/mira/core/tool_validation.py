"""Contract validation middleware for tool calls (e02-f04, ADR-009/037).

Plugs into the composable middleware pipeline: validates each tool call against
its contract before execution, rejects malformed input with a structured error,
and relies on guardrail_out (downstream in the pipeline) to treat tool output as
untrusted.
"""

from __future__ import annotations

from typing import Any

from mira.core.middleware import NextFn, RequestContext
from mira.tools.contract import ToolContract, ToolValidationError, validate_input

TOOL_CONTRACT_KEY = "tool_contract"
TOOL_PAYLOAD_KEY = "tool_payload"


class ToolValidationMiddleware:
    """Validates tool input against its contract before the handler runs."""

    async def __call__(self, ctx: RequestContext, call_next: NextFn) -> Any:
        contract: ToolContract | None = ctx.attributes.get(TOOL_CONTRACT_KEY)
        if contract is None:
            return await call_next()

        payload = ctx.attributes.get(TOOL_PAYLOAD_KEY)
        if not isinstance(payload, dict):
            raise ToolValidationError(
                f"Invalid input for tool {contract.name!r}: payload must be a dict",
                details=["expected=dict"],
            )

        validate_input(contract, payload)
        return await call_next()
