"""Tests for model gateway and LangGraph adapter (ADR-010)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from mira.model.gateway import Gateway
from mira.orchestration.model_adapter import GatewayChatModel
from mira.providers.protocols import ILLMProvider


class FakeLLMProvider:
    def complete(self, prompt: str, *, model: str | None = None) -> str:
        suffix = f" model={model}" if model else ""
        return f"fake:{prompt}{suffix}"

    def embed(self, text: str) -> list[float]:
        return [float(len(text))]


class FakeBundle:
    def __init__(self, llm: ILLMProvider) -> None:
        self.llm = llm


def test_gateway_delegates_complete_and_embed() -> None:
    fake = FakeLLMProvider()
    gateway = Gateway(FakeBundle(fake))  # type: ignore[arg-type]

    assert gateway.complete("hello", model="test-model") == "fake:hello model=test-model"
    assert gateway.embed("abc") == [3.0]


def test_adapter_routes_chat_through_gateway() -> None:
    fake = FakeLLMProvider()
    gateway = Gateway(FakeBundle(fake))  # type: ignore[arg-type]
    chat_model = GatewayChatModel(llm=gateway)

    response = chat_model.invoke([HumanMessage(content="route me")])

    # role label is preserved when flattening (M2)
    assert response.content == "fake:Human: route me"


def test_gateway_conforms_to_illmprovider() -> None:
    # L1: lock the ADR-010 contract that Gateway is an ILLMProvider.
    gateway = Gateway(FakeBundle(FakeLLMProvider()))  # type: ignore[arg-type]
    assert isinstance(gateway, ILLMProvider)


def test_adapter_preserves_roles_across_multi_turn() -> None:
    # M2: multi-turn history keeps role labels rather than flattening blindly.
    gateway = Gateway(FakeBundle(FakeLLMProvider()))  # type: ignore[arg-type]
    chat_model = GatewayChatModel(llm=gateway)

    response = chat_model.invoke(
        [
            SystemMessage(content="be terse"),
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
            HumanMessage(content="more"),
        ]
    )

    assert response.content == "fake:System: be terse\nHuman: hi\nAssistant: hello\nHuman: more"
