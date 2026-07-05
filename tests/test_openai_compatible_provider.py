"""Tests for the OpenAI-compatible LLM provider (network-free: no .invoke()).

These exercise construction, env resolution, and the fail-closed missing-URL path. They
do NOT call ``complete``/``chat_model`` (which would require ``langchain-openai`` and a
reachable endpoint) — that is covered by the live model-layer check in the plan.
"""

from __future__ import annotations

import pytest

from mira.providers.openai_compatible import (
    MissingLLMConfigError,
    OpenAICompatibleLLMProvider,
)
from mira.providers.protocols import ILLMProvider


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_explicit_args_construct_and_conform() -> None:
    provider = OpenAICompatibleLLMProvider(
        base_url="http://localhost:11434/v1",
        api_key="k",
        model="llama3.1",
    )
    assert isinstance(provider, ILLMProvider)
    assert provider.model_name == "llama3.1"


def test_resolves_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "mpt-7b")
    provider = OpenAICompatibleLLMProvider()
    assert provider.model_name == "mpt-7b"


def test_missing_base_url_is_fail_closed() -> None:
    with pytest.raises(MissingLLMConfigError, match="LLM_BASE_URL is required"):
        OpenAICompatibleLLMProvider()


def test_embed_not_supported() -> None:
    provider = OpenAICompatibleLLMProvider(base_url="http://x/v1")
    with pytest.raises(NotImplementedError, match="embeddings are a separate provider"):
        provider.embed("text")
