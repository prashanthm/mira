"""AWS provider bundle — stub implementations with lazy SDK imports.

``boto3`` is imported lazily and is intentionally NOT a declared dependency yet:
these are structural stubs, so calling any method raises ``NotImplementedError``
after a best-effort import. The first real AWS implementation task must add
``boto3`` (e.g. as an optional ``[aws]`` extra) to ``pyproject.toml``; until
then a call on a host without boto3 surfaces ``ImportError`` before the stub's
``NotImplementedError``.
"""

from __future__ import annotations

from mira.providers.bundle import ProviderBundle
from mira.providers.protocols import (
    ILLMProvider,
    IObjectStore,
    IObservability,
    ISecretsProvider,
    IStateStore,
)


class AwsLLMProvider:
    def complete(self, prompt: str, *, model: str | None = None) -> str:
        import boto3  # noqa: F401 — lazy SDK import; real impl in a later feature

        _ = (prompt, model)
        raise NotImplementedError("AWS LLM provider is not implemented yet")

    def embed(self, text: str) -> list[float]:
        import boto3  # noqa: F401

        _ = text
        raise NotImplementedError("AWS LLM provider is not implemented yet")


class AwsSecretsProvider:
    def get_secret(self, key: str) -> str:
        import boto3  # noqa: F401

        _ = key
        raise NotImplementedError("AWS secrets provider is not implemented yet")


class AwsObjectStore:
    def put(self, key: str, data: bytes) -> None:
        import boto3  # noqa: F401

        _ = (key, data)
        raise NotImplementedError("AWS object store is not implemented yet")

    def get(self, key: str) -> bytes | None:
        import boto3  # noqa: F401

        _ = key
        raise NotImplementedError("AWS object store is not implemented yet")


class AwsStateStore:
    def get(self, key: str) -> str | None:
        import boto3  # noqa: F401

        _ = key
        raise NotImplementedError("AWS state store is not implemented yet")

    def set(self, key: str, value: str) -> None:
        import boto3  # noqa: F401

        _ = (key, value)
        raise NotImplementedError("AWS state store is not implemented yet")


class AwsObservability:
    def log(self, message: str, *, level: str = "info", **fields: object) -> None:
        import boto3  # noqa: F401

        _ = (message, level, fields)
        raise NotImplementedError("AWS observability is not implemented yet")

    def metric(self, name: str, value: float, **tags: str) -> None:
        import boto3  # noqa: F401

        _ = (name, value, tags)
        raise NotImplementedError("AWS observability is not implemented yet")

    def span(self, name: str) -> object:
        import boto3  # noqa: F401

        _ = name
        raise NotImplementedError("AWS observability is not implemented yet")


def build_aws_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm=AwsLLMProvider(),
        secrets=AwsSecretsProvider(),
        object_store=AwsObjectStore(),
        state_store=AwsStateStore(),
        observability=AwsObservability(),
    )
