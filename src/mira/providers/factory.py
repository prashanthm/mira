"""PLATFORM-driven provider factory with a URL-driven LLM override (ADR-002, ADR-010).

Two orthogonal axes, each its own config knob (never a single ``local``/``aws`` branch):

* **Infra platform** (``PLATFORM``) selects the state/secrets/object-store/observability
  bundle — ``local`` (in-memory) or ``aws`` (cloud). Unset falls back to ``local`` so a
  bare ``get_providers()`` boots the dev bundle rather than failing fast; ``build_app``
  passes the resolved profile's platform explicitly.
* **Model** (``LLM_BASE_URL``) selects the LLM independently. When set, the bundle's LLM
  is the OpenAI-compatible provider pointed at that URL — *regardless of platform* — so a
  local-infra boot can drive a remote model and an AWS-infra boot can drive a local one
  (AWS Bedrock is reached by pointing ``LLM_BASE_URL`` at a LiteLLM proxy). When unset,
  the platform's own LLM is used (the in-memory echo stub for ``local``).

Phase-1 note retained from the original factory: protocols live in
``mira.providers.protocols`` (not ``mira.interfaces``) and the factory is ``get_providers``
(vs ADR-002's ``build_providers``) — naming only, reconcile in a docs follow-up.
"""

from __future__ import annotations

import os
from dataclasses import replace

from mira.providers.bundle import ProviderBundle
from mira.providers.openai_compatible import LLM_BASE_URL_ENV

DEFAULT_PLATFORM = "local"


def _build_infra_bundle(platform: str) -> ProviderBundle:
    """Resolve the platform bundle (state/secrets/object/observability + its own LLM)."""
    match platform:
        case "local":
            from mira.providers.local import build_local_bundle

            return build_local_bundle()
        case "aws":
            from mira.providers.aws import build_aws_bundle

            return build_aws_bundle()
        case _:
            raise ValueError(f"Unsupported PLATFORM: {platform!r}")


def _llm_override() -> object | None:
    """Build the OpenAI-compatible LLM if ``LLM_BASE_URL`` is configured, else ``None``."""
    if not os.environ.get(LLM_BASE_URL_ENV):
        return None
    from mira.providers.openai_compatible import OpenAICompatibleLLMProvider

    return OpenAICompatibleLLMProvider()


def get_providers(platform: str | None = None) -> ProviderBundle:
    """Resolve the provider bundle from ``PLATFORM`` (infra) and ``LLM_BASE_URL`` (model).

    ``platform`` defaults to ``$PLATFORM`` then :data:`DEFAULT_PLATFORM`. If
    ``LLM_BASE_URL`` is set, the bundle's LLM is swapped for the OpenAI-compatible
    provider so the model endpoint is decoupled from the infra platform.
    """
    resolved = platform if platform is not None else os.environ.get("PLATFORM")
    if not resolved:
        resolved = DEFAULT_PLATFORM

    bundle = _build_infra_bundle(resolved)

    llm = _llm_override()
    if llm is not None:
        bundle = replace(bundle, llm=llm)

    return bundle
