"""Tests for GatewayChatModel tool binding (ADR-010 tool calling).

A tool-aware provider (one exposing ``chat(messages, tools=...)`` → ChatResult/ToolCall,
like the OpenAI-compatible provider) drives autonomous tool selection through bind_tools;
a text-only provider (no ``chat``) falls back to ``complete``. Both verified with fakes —
no network, no real LLM.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from mira.orchestration.model_adapter import GatewayChatModel
from mira.providers.openai_compatible import ChatResult, ToolCall


@tool
def catalog_search(kind: str) -> str:
    """Search Catalog records by kind."""
    return f"searched {kind}"


class FakeToolAwareProvider:
    """Provider exposing the tool-aware ``chat`` seam; records the tools it was handed."""

    def __init__(self, result: ChatResult) -> None:
        self._result = result
        self.seen_tools: list[dict] | None = None

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        return f"text:{prompt}"

    def embed(self, text: str) -> list[float]:
        return [1.0]

    def chat(self, messages, *, model=None, tools=None, tool_choice="auto") -> ChatResult:
        self.seen_tools = tools
        return self._result


class TextOnlyProvider:
    def complete(self, prompt: str, *, model: str | None = None) -> str:
        return f"text:{prompt}"

    def embed(self, text: str) -> list[float]:
        return [1.0]


def test_bound_tools_route_through_chat_and_surface_tool_calls() -> None:
    result = ChatResult(
        text="",
        tool_calls=(ToolCall(id="c1", name="catalog_search", arguments='{"kind":"well"}'),),
    )
    provider = FakeToolAwareProvider(result)
    model = GatewayChatModel(provider).bind_tools([catalog_search])

    message = model.invoke([HumanMessage(content="find wells")])

    # The model selected the tool with parsed args.
    assert len(message.tool_calls) == 1
    call = message.tool_calls[0]
    assert call["name"] == "catalog_search"
    assert call["args"] == {"kind": "well"}
    # The tool was converted to an OpenAI function spec and handed to the provider.
    assert provider.seen_tools is not None
    assert provider.seen_tools[0]["function"]["name"] == "catalog_search"


def test_dotted_tool_name_is_sanitized_for_provider_and_mapped_back() -> None:
    # MCP tools are dotted (vantage.positions); OpenAI/DeepSeek reject '.' in a
    # function name (^[a-zA-Z0-9_-]+$). The adapter must send a safe name and map
    # the model's tool-call back to the real dotted name.
    from langchain_core.tools import StructuredTool

    dotted = StructuredTool.from_function(
        lambda account="all": account, name="vantage.portfolio_snapshot",
        description="portfolio DNA",
    )
    # the model replies referring to the SAFE name (what the provider saw).
    result = ChatResult(
        text="",
        tool_calls=(ToolCall(id="c1", name="vantage_portfolio_snapshot",
                             arguments='{"account":"all"}'),),
    )
    provider = FakeToolAwareProvider(result)
    model = GatewayChatModel(provider).bind_tools([dotted])
    message = model.invoke([HumanMessage(content="analyze my portfolio")])

    # provider received a pattern-valid name (no dot)
    assert provider.seen_tools[0]["function"]["name"] == "vantage_portfolio_snapshot"
    # but the dispatched tool call carries the REAL dotted name
    assert message.tool_calls[0]["name"] == "vantage.portfolio_snapshot"
    assert message.tool_calls[0]["args"] == {"account": "all"}


def test_malformed_tool_args_fall_back_to_raw() -> None:
    result = ChatResult(
        text="",
        tool_calls=(ToolCall(id="c1", name="catalog_search", arguments="{not json"),),
    )
    model = GatewayChatModel(FakeToolAwareProvider(result)).bind_tools([catalog_search])
    message = model.invoke([HumanMessage(content="x")])
    assert message.tool_calls[0]["args"] == {"_raw": "{not json"}


def test_text_only_provider_ignores_binding_and_uses_complete() -> None:
    # A provider with no ``chat`` seam falls back to the text path even when tools bound.
    model = GatewayChatModel(TextOnlyProvider()).bind_tools([catalog_search])
    message = model.invoke([HumanMessage(content="hi")])
    assert message.content == "text:Human: hi"
    assert not message.tool_calls
