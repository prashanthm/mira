"""Provider bundle container (ADR-002)."""

from __future__ import annotations

from dataclasses import dataclass

from mira.providers.protocols import (
    ILLMProvider,
    IObjectStore,
    IObservability,
    ISecretsProvider,
    IStateStore,
)


@dataclass(frozen=True)
class ProviderBundle:
    llm: ILLMProvider
    secrets: ISecretsProvider
    object_store: IObjectStore
    state_store: IStateStore
    observability: IObservability
