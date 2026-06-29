"""JSONL/JSON-file-backed DataProvider.

The ONLY product-specific knowledge is the resource→path map, supplied by config.
Reads .jsonl (one object per line) or .json (a single object/array).
"""
from __future__ import annotations

import json
import os


class JsonlProvider:
    def __init__(self, provider_name: str, paths: dict[str, str], base_dir: str = ""):
        self._name = provider_name
        self._paths = paths
        self._base = base_dir

    def name(self) -> str:
        return self._name

    def resources(self) -> list[str]:
        return list(self._paths.keys())

    def _resolve(self, path: str) -> str:
        if os.path.isabs(path) or not self._base:
            return path
        return os.path.join(self._base, path)

    def read(self, resource: str, limit: int | None = None) -> list[dict] | dict:
        if resource not in self._paths:
            raise KeyError(f"unknown resource '{resource}' (have: {self.resources()})")
        path = self._resolve(self._paths[resource])
        if not os.path.exists(path):
            return [] if path.endswith(".jsonl") else {}

        if path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}

        # .jsonl
        rows: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if limit is not None and limit >= 0:
            rows = rows[-limit:]
        return rows
