"""Tests for provider Protocols, factory, and bundles."""

from __future__ import annotations

import pytest

from mira.providers.bundle import ProviderBundle
from mira.providers.factory import get_providers
from mira.providers.protocols import (
    ILLMProvider,
    IObjectStore,
    IObservability,
    ISecretsProvider,
    IStateStore,
)


def _assert_bundle_conforms(bundle: ProviderBundle) -> None:
    assert isinstance(bundle.llm, ILLMProvider)
    assert isinstance(bundle.secrets, ISecretsProvider)
    assert isinstance(bundle.object_store, IObjectStore)
    assert isinstance(bundle.state_store, IStateStore)
    assert isinstance(bundle.observability, IObservability)


@pytest.fixture(autouse=True)
def _no_llm_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # LLM_BASE_URL swaps the bundle LLM for the OpenAI-compatible provider; clear it so
    # the platform-bundle tests below see the platform's own (echo-stub) LLM.
    monkeypatch.delenv("LLM_BASE_URL", raising=False)


def test_local_bundle_resolves_and_conforms() -> None:
    bundle = get_providers(platform="local")
    _assert_bundle_conforms(bundle)
    assert bundle.llm.complete("hello") == "[local:default] hello"
    assert bundle.secrets.get_secret("db") == "local-secret:db"


def test_aws_bundle_resolves_and_conforms() -> None:
    bundle = get_providers(platform="aws")
    _assert_bundle_conforms(bundle)


def test_unknown_platform_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported PLATFORM"):
        get_providers(platform="azure")


def test_unset_platform_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unset PLATFORM now falls back to the local infra bundle (was: fail-fast). The
    # deployment profile passes platform explicitly via build_app; this default keeps a
    # bare get_providers() booting the dev bundle.
    monkeypatch.delenv("PLATFORM", raising=False)
    bundle = get_providers()
    _assert_bundle_conforms(bundle)
    assert bundle.llm.complete("x") == "[local:default] x"


def test_env_var_resolves_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    # AC-4 env-driven path: PLATFORM env (no explicit arg) resolves a bundle.
    monkeypatch.setenv("PLATFORM", "local")
    bundle = get_providers()
    _assert_bundle_conforms(bundle)
    assert bundle.llm.complete("x") == "[local:default] x"


def test_llm_base_url_overrides_bundle_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    # When LLM_BASE_URL is set, the bundle LLM is the OpenAI-compatible provider
    # regardless of platform — the model is decoupled from the infra platform.
    from mira.providers.openai_compatible import OpenAICompatibleLLMProvider

    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")
    bundle = get_providers(platform="local")
    _assert_bundle_conforms(bundle)
    assert isinstance(bundle.llm, OpenAICompatibleLLMProvider)
    # Infra providers still come from the platform bundle.
    assert bundle.secrets.get_secret("db") == "local-secret:db"
