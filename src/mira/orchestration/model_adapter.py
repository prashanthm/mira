"""LangGraph chat-model bridge to ``ILLMProvider`` (ADR-007 containment, ADR-010).

Tool calling (ADR-010, now wired): a provider that exposes a tool-aware ``chat(messages,
tools=...)`` returning ``ChatResult``/``ToolCall`` (the OpenAI-compatible provider) lets
this adapter honour ``bind_tools()`` — it converts bound LangChain tools to OpenAI tool
specs, calls the provider, and maps any requested calls onto ``AIMessage.tool_calls`` so
LangGraph/the runtime sees autonomous tool selection. A text-only provider (the in-memory
echo stub, which has no ``chat``) transparently falls back to ``complete()``, so existing
behavior is unchanged when no tool-capable provider is in play.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, Callable

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from mira.providers.protocols import ILLMProvider


class GatewayChatModel(BaseChatModel):
    """Thin ``BaseChatModel`` adapter that routes chat calls through ``ILLMProvider``."""

    default_model: str | None = None

    def __init__(
        self,
        llm: ILLMProvider,
        *,
        default_model: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(default_model=default_model, **kwargs)
        self._llm = llm
        # OpenAI tool specs captured by ``bind_tools``; empty = text-only path.
        self._tool_specs: list[dict[str, Any]] = []

    @property
    def _llm_type(self) -> str:
        return "gateway"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        **kwargs: Any,
    ) -> Runnable[Any, BaseMessage]:
        """Bind tools for selection; convert to OpenAI specs the provider's ``chat`` uses.

        Returns ``self`` rebound (LangChain ``bind`` semantics) so the standard
        ``model.bind_tools(...)`` call site works. The specs are stored on the model; the
        provider must expose a tool-aware ``chat`` for them to take effect.
        """
        self._tool_specs = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(**kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # ``stop`` sequences are intentionally not yet wired through to the
        # provider (ADR-010 streaming is a later feature); document rather than
        # silently drop on the hot path. (L2)
        del stop, run_manager
        model = kwargs.get("model", self.default_model)
        chat = getattr(self._llm, "chat", None)
        if self._tool_specs and callable(chat):
            result = chat(
                self._render_chat_messages(messages),
                model=model,
                tools=self._tool_specs,
            )
            tool_calls = [
                {
                    "name": call.name,
                    "args": _safe_json(call.arguments),
                    "id": call.id or str(uuid.uuid4()),
                    "type": "tool_call",
                }
                for call in result.tool_calls
            ]
            message = AIMessage(content=result.text, tool_calls=tool_calls)
            return ChatResult(generations=[ChatGeneration(message=message)])

        prompt = self._render_messages(messages)
        text = self._llm.complete(prompt, model=model)
        generation = ChatGeneration(message=AIMessage(content=text))
        return ChatResult(generations=[generation])

    @staticmethod
    def _render_chat_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """Map LangChain messages to OpenAI chat-message dicts for the provider's ``chat``."""
        role_for = {"system": "system", "human": "user", "ai": "assistant"}
        return [
            {"role": role_for.get(m.type, "user"), "content": str(m.content)}
            for m in messages
        ]

    @staticmethod
    def _render_messages(messages: list[BaseMessage]) -> str:
        """Flatten chat history with role labels so multi-turn context is not
        lost when collapsing to a single prompt string (M2)."""
        role_labels = {"system": "System", "human": "Human", "ai": "Assistant"}
        lines = []
        for message in messages:
            label = role_labels.get(message.type, message.type.capitalize())
            lines.append(f"{label}: {message.content}")
        return "\n".join(lines)


def _safe_json(arguments: str) -> dict[str, Any]:
    """Parse a tool call's JSON-string arguments to a dict, tolerating malformed output.

    Models occasionally emit non-JSON or partial arguments; rather than crash the turn, we
    surface the raw string under ``_raw`` so the dispatch layer can decide how to handle it.
    """
    try:
        parsed = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return {"_raw": arguments}
    return parsed if isinstance(parsed, dict) else {"_raw": arguments}
