"""Tests for the mira-chat CLI helpers."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

from mira.chat import _autodetect_model


class _FakeUrlResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> io.BytesIO:
        return io.BytesIO(self._payload)

    def __exit__(self, *_: object) -> bool:
        return False


def test_autodetect_model_picks_tool_capable_hint() -> None:
    payload = json.dumps({"data": [{"id": "qwen2.5:7b"}, {"id": "llama3:latest"}]}).encode()
    with patch(
        "mira.chat.urllib.request.urlopen",
        return_value=_FakeUrlResponse(payload),
    ):
        assert _autodetect_model("http://localhost:11434/v1", "key") == "qwen2.5:7b"


def test_autodetect_model_rejects_non_tool_models_only() -> None:
    payload = json.dumps({"data": [{"id": "llama3:latest"}]}).encode()
    with patch(
        "mira.chat.urllib.request.urlopen",
        return_value=_FakeUrlResponse(payload),
    ):
        assert _autodetect_model("http://localhost:11434/v1", "key") is None


def test_autodetect_model_returns_none_when_endpoint_down() -> None:
    with patch("mira.chat.urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert _autodetect_model("http://localhost:11434/v1", "key") is None
