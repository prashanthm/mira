"""Local provider bundle — in-memory implementations, no cloud SDK."""

from __future__ import annotations

from mira.providers.bundle import ProviderBundle
from mira.providers.protocols import (
    ILLMProvider,
    IObjectStore,
    IObservability,
    ISecretsProvider,
    IStateStore,
)


class LocalLLMProvider:
    def complete(self, prompt: str, *, model: str | None = None) -> str:
        return f"[local:{model or 'default'}] {prompt}"

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


class LocalSecretsProvider:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get_secret(self, key: str) -> str:
        return self._secrets.setdefault(key, f"local-secret:{key}")


class LocalObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    def get(self, key: str) -> bytes | None:
        return self._objects.get(key)


class LocalStateStore:
    def __init__(self) -> None:
        self._state: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._state.get(key)

    def set(self, key: str, value: str) -> None:
        self._state[key] = value


class LocalObservability:
    def log(self, message: str, *, level: str = "info", **fields: object) -> None:
        _ = (message, level, fields)

    def metric(self, name: str, value: float, **tags: str) -> None:
        _ = (name, value, tags)

    def span(self, name: str) -> object:
        return {"name": name}


def build_local_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm=LocalLLMProvider(),
        secrets=LocalSecretsProvider(),
        object_store=LocalObjectStore(),
        state_store=LocalStateStore(),
        observability=LocalObservability(),
    )
