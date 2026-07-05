"""Provider Protocol interfaces (ADR-002)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ILLMProvider(Protocol):
    def complete(self, prompt: str, *, model: str | None = None) -> str: ...

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class ISecretsProvider(Protocol):
    def get_secret(self, key: str) -> str: ...


@runtime_checkable
class IObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...


@runtime_checkable
class IStateStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


@runtime_checkable
class IObservability(Protocol):
    def log(self, message: str, *, level: str = "info", **fields: Any) -> None: ...

    def metric(self, name: str, value: float, **tags: str) -> None: ...

    def span(self, name: str) -> Any: ...
