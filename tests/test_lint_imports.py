"""Tests for tools/lint_imports.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINTER = ROOT / "tools" / "lint_imports.py"


def _run(*paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINTER), *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_clean_src_saa_passes() -> None:
    result = _run("src/mira")
    assert result.returncode == 0, result.stdout + result.stderr


def test_bad_cloud_import_fails() -> None:
    result = _run("tests/fixtures/lint/bad_cloud_import")
    assert result.returncode != 0
    assert "boto3" in result.stdout


def test_bad_langchain_import_fails() -> None:
    result = _run("tests/fixtures/lint/bad_langchain_import")
    assert result.returncode != 0
    assert "langchain" in result.stdout
