"""The data-provider seam.

A DataProvider gives the agent read-only access to named resources without the
framework knowing where the data lives. Today it's backed by JSONL files; later a
SQLite/HTTP backend can implement the same protocol with zero agent changes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DataProvider(Protocol):
    def name(self) -> str:
        """Human-readable provider name (e.g. 'sentinel')."""
        ...

    def resources(self) -> list[str]:
        """The resource keys this provider can read."""
        ...

    def read(self, resource: str, limit: int | None = None) -> list[dict] | dict:
        """Return the data for a resource. Raises KeyError for unknown resources."""
        ...
