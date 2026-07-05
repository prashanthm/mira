"""Tests for the ``mira-insights`` CLI (monkeypatched discovery — no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mira import insights_cli
from mira.orchestration.insights import ADVISORY_DISCLAIMER

from tests.fake_vantage import fake_vantage_mcp_tools


def _patch_discovery(monkeypatch: pytest.MonkeyPatch) -> list[list]:
    """Route the CLI's tool discovery to the fake vantage tools; log registries."""
    seen: list[list] = []

    def fake_load(registry, **_kwargs):
        seen.append(list(registry))
        return fake_vantage_mcp_tools()

    monkeypatch.setattr(insights_cli, "load_mcp_tools", fake_load)
    return seen


def test_happy_path_prints_report_json(monkeypatch, capsys) -> None:
    seen = _patch_discovery(monkeypatch)

    exit_code = insights_cli.main(["--domain", "advisor", "--mcp", "http://x:8640/mcp"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated_for"] == "advisor"
    assert payload["confidence"] == "medium"
    assert ADVISORY_DISCLAIMER in payload["caveats"]
    assert payload["observations"][0]["provenance"]["source_type"] == "vantage"
    # The CLI declared exactly the one server the flag named.
    (registry,) = seen
    assert registry[0].url == "http://x:8640/mcp"
    assert registry[0].name == "vantage"


def test_out_flag_appends_jsonl(monkeypatch, capsys, tmp_path: Path) -> None:
    _patch_discovery(monkeypatch)
    out = tmp_path / "insights.jsonl"

    assert insights_cli.main(["--out", str(out)]) == 0
    assert insights_cli.main(["--out", str(out)]) == 0
    capsys.readouterr()

    lines = out.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        assert record["generated_for"] == "advisor"


def test_unreachable_server_exits_1_with_clean_message(monkeypatch, capsys) -> None:
    def failing_load(_registry, **_kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(insights_cli, "load_mcp_tools", failing_load)

    exit_code = insights_cli.main(["--mcp", "http://127.0.0.1:9/mcp"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "mira-insights: cannot reach MCP server at http://127.0.0.1:9/mcp" in err
    assert "connection refused" in err
    assert "Traceback" not in err


def test_server_without_vantage_tools_exits_1(monkeypatch, capsys) -> None:
    monkeypatch.setattr(insights_cli, "load_mcp_tools", lambda _r, **_k: [])

    assert insights_cli.main([]) == 1
    assert "exposes no vantage.* tools" in capsys.readouterr().err


def test_unsupported_domain_exits_1(monkeypatch, capsys) -> None:
    _patch_discovery(monkeypatch)

    assert insights_cli.main(["--domain", "finance"]) == 1
    assert "unsupported domain 'finance'" in capsys.readouterr().err
