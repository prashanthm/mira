"""OpenAI-compatible LLM provider — point at any ``/v1`` chat endpoint (ADR-010, ADR-002, ADR-007).

The LLM is a *URL*, not a platform branch: Ollama, vLLM, TGI, LM Studio, Together, and
Groq all speak the OpenAI ``/v1/chat/completions`` API directly, and **AWS Bedrock is
reached by pointing ``LLM_BASE_URL`` at a LiteLLM proxy** — so no boto3/SigV4 lives in app
code. Configuration is three env knobs: ``LLM_BASE_URL``, ``LLM_API_KEY``, ``LLM_MODEL``.

This provider uses the **plain ``openai`` SDK, never langchain** — the LangChain framework
is contained to ``orchestration/`` (ADR-007, enforced by
``test_no_langgraph_import_outside_orchestration``). The orchestration layer adapts this
provider to LangChain; the provider itself stays framework-agnostic. The ``openai`` SDK is
imported lazily (ADR-002) and is an optional ``[llm]`` extra, so the default/echo-stub
import path stays SDK-free.

It satisfies :class:`~mira.providers.protocols.ILLMProvider` (``complete`` / ``embed``) for
the text path, and adds :meth:`chat` — a framework-free tool-calling call returning a
:class:`ChatResult` (assistant text + any requested :class:`ToolCall`s) that the
orchestration layer maps onto LangChain tool calls for autonomous tool selection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# Env knobs (the only configuration this provider reads).
LLM_BASE_URL_ENV = "LLM_BASE_URL"
LLM_API_KEY_ENV = "LLM_API_KEY"
LLM_MODEL_ENV = "LLM_MODEL"

# Some OpenAI-compatible servers (e.g. a default Ollama build) ignore the key but the
# client still requires a non-empty string; use a harmless placeholder when unset so a
# keyless local endpoint works without forcing operators to invent a value.
_PLACEHOLDER_API_KEY = "not-needed"


class MissingLLMConfigError(ValueError):
    """Raised when the OpenAI-compatible provider is selected without an endpoint URL."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool the model asked to invoke: tool name + raw JSON-string arguments."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Outcome of a tool-aware chat turn: assistant text and/or requested tool calls."""

    text: str
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class OpenAICompatibleLLMProvider:
    """``ILLMProvider`` backed by the ``openai`` SDK against any ``/v1`` URL.

    ``base_url``/``api_key``/``model`` default to the ``LLM_BASE_URL``/``LLM_API_KEY``/
    ``LLM_MODEL`` env vars; pass them explicitly to construct without touching the
    environment (used by tests). The client is built lazily on first use and cached, so
    importing this module never requires the SDK or a reachable endpoint.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = base_url if base_url is not None else os.environ.get(LLM_BASE_URL_ENV)
        self._api_key = api_key if api_key is not None else os.environ.get(LLM_API_KEY_ENV)
        self._model = model if model is not None else os.environ.get(LLM_MODEL_ENV)
        if not self._base_url:
            raise MissingLLMConfigError(
                f"{LLM_BASE_URL_ENV} is required for the OpenAI-compatible LLM provider"
            )
        # Built lazily so import/construction stays SDK-free and network-free.
        self._client: Any | None = None

    @property
    def model_name(self) -> str | None:
        """The default model id this provider was configured with (``LLM_MODEL``)."""
        return self._model

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - only without the [llm] extra
                raise ImportError(
                    "openai is required for the OpenAI-compatible LLM provider; install "
                    "the optional extra: pip install '.[llm]'"
                ) from exc
            self._client = OpenAI(
                base_url=self._base_url,
                api_key=self._api_key or _PLACEHOLDER_API_KEY,
            )
        return self._client

    def _resolved_model(self, model: str | None) -> str:
        resolved = model or self._model
        if not resolved:
            raise MissingLLMConfigError(
                f"a model is required: set {LLM_MODEL_ENV} or pass model=..."
            )
        return resolved

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """Single-prompt completion returning the assistant text (``ILLMProvider``)."""
        return self.chat([{"role": "user", "content": prompt}], model=model).text

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> ChatResult:
        """Tool-aware chat turn over the OpenAI ``/v1/chat/completions`` API.

        ``tools`` is a list of OpenAI function-tool specs
        (``{"type": "function", "function": {...}}``). Returns the assistant text plus any
        :class:`ToolCall`s the model requested — framework-free, so ``orchestration/`` owns
        the LangChain mapping.
        """
        client = self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": self._resolved_model(model),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        completion = client.chat.completions.create(**kwargs)
        message = completion.choices[0].message
        raw_calls = getattr(message, "tool_calls", None) or ()
        tool_calls = tuple(
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in raw_calls
        )
        return ChatResult(text=message.content or "", tool_calls=tool_calls)

    def embed(self, text: str) -> list[float]:
        """Embeddings are not served over the chat endpoint (ADR-010 follow-up).

        Embeddings belong to a separate ``/v1/embeddings`` model and are out of scope for
        the chat-tool-calling path this provider exists for; wire a dedicated embeddings
        provider when the semantic spine needs vectors rather than overloading this one.
        """
        _ = text
        raise NotImplementedError(
            "OpenAI-compatible provider serves chat completions only; embeddings are a "
            "separate provider (ADR-010 follow-up)"
        )
