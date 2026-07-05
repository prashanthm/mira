"""Tests for the mira-scaffold domain generator (ADR-016).

Generates into ``tmp_path`` (repo-shaped layout), asserts the artifact set,
refuse-to-overwrite behaviour, sanitize-cleanliness, and — the ADR-016
guarantee — that the GENERATED tests pass as generated (run via a subprocess
pytest against the generated tree).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from mira.scaffold import ScaffoldError, main, new_domain

REPO_SRC = Path(__file__).resolve().parents[1] / "src"

# Mirrors the Makefile sanitize-check patterns (bracket classes keep this
# test from matching itself), plus the word-bounded extras from the Phase-F
# banned-string list.
_BANNED = re.compile(
    r"4[7]lining|os[d]u|\bed[i]\b|subsur[f]ace|geosc[i]ence|petre[l]|ppd[m]"
    r"|seg-?[y]\b|osiso[f]t|\bsa[a]\b|\bmin[i]ng\b|\bla[s]\b",
    re.IGNORECASE,
)

_CONNECTOR_FILES = (
    "src/mira/connectors/inventory.py",
    "src/mira/orchestration/specialists/inventory.py",
    "tests/test_inventory_connector.py",
    "tests/test_inventory_specialist.py",
    "specs/inventory-specialist/spec.md",
    "specs/inventory-specialist/plan.md",
    "specs/inventory-specialist/tasks.md",
    "evals/goldens/inventory.jsonl.example",
)

# The package-merge shim the scaffold test harness needs: generated modules
# live under tmp_path/src/mira/... while the real ``mira`` package resolves
# from the repo install, so extend the package __path__s. Dropping scaffold
# output into the real repo needs no shim — files land inside the package.
_CONFTEST_SHIM = """\
from pathlib import Path

import mira.connectors
import mira.orchestration.specialists

_SRC = Path(__file__).resolve().parent / "src"
mira.connectors.__path__.append(str(_SRC / "mira" / "connectors"))
mira.orchestration.specialists.__path__.append(
    str(_SRC / "mira" / "orchestration" / "specialists")
)
"""


def _generate_inventory(out: Path) -> list[Path]:
    return new_domain("inventory", "inventory.", out)


def test_generates_expected_connector_domain_files(tmp_path: Path) -> None:
    written = _generate_inventory(tmp_path)
    for rel in _CONNECTOR_FILES:
        assert (tmp_path / rel).exists(), f"missing generated file: {rel}"
    assert sorted(written) == sorted(tmp_path / rel for rel in _CONNECTOR_FILES)


def test_refuses_to_overwrite_existing_files(tmp_path: Path) -> None:
    _generate_inventory(tmp_path)
    with pytest.raises(ScaffoldError, match="refusing to overwrite"):
        _generate_inventory(tmp_path)


def test_partial_collision_writes_nothing(tmp_path: Path) -> None:
    collision = tmp_path / "specs" / "inventory-specialist" / "spec.md"
    collision.parent.mkdir(parents=True)
    collision.write_text("pre-existing", encoding="utf-8")

    with pytest.raises(ScaffoldError, match="refusing to overwrite"):
        _generate_inventory(tmp_path)

    assert collision.read_text(encoding="utf-8") == "pre-existing"
    assert not (tmp_path / "src/mira/connectors/inventory.py").exists()


def test_mcp_kind_skips_connector_and_notes_mcp_binding(tmp_path: Path) -> None:
    written = new_domain("signals", "signals.", tmp_path, domain_kind="mcp")

    rels = {p.relative_to(tmp_path).as_posix() for p in written}
    assert "src/mira/connectors/signals.py" not in rels
    assert "tests/test_signals_connector.py" not in rels
    assert "src/mira/orchestration/specialists/signals.py" in rels

    specialist = (tmp_path / "src/mira/orchestration/specialists/signals.py").read_text(
        encoding="utf-8"
    )
    assert "MCP_SERVERS" in specialist
    assert "mcp_registry" in specialist


def test_specialist_docstring_carries_card_snippet_and_registration(tmp_path: Path) -> None:
    _generate_inventory(tmp_path)
    specialist = (
        tmp_path / "src/mira/orchestration/specialists/inventory.py"
    ).read_text(encoding="utf-8")
    assert "card_for_domain" in specialist
    assert "registry.register(" in specialist
    assert "REPRESENTATIVE_INVENTORY_QUERY" in specialist
    assert "evals/goldens/inventory.jsonl.example" in specialist


def test_generated_output_is_sanitize_clean(tmp_path: Path) -> None:
    written = _generate_inventory(tmp_path)
    written += new_domain("signals", "signals.", tmp_path, domain_kind="mcp")
    for path in written:
        match = _BANNED.search(path.read_text(encoding="utf-8"))
        assert match is None, f"banned string {match.group(0)!r} in {path}"


def test_prefix_is_normalized_and_bad_inputs_fail(tmp_path: Path) -> None:
    written = new_domain("widgets", "widgets", tmp_path)  # trailing dot appended
    connector = next(p for p in written if p.name == "widgets.py" and "connectors" in str(p))
    assert 'frozenset({"widgets."})' in (
        tmp_path / "src/mira/orchestration/specialists/widgets.py"
    ).read_text(encoding="utf-8")
    assert '"connector:widgets:lookup"' in connector.read_text(encoding="utf-8")

    with pytest.raises(ScaffoldError, match="domain name"):
        new_domain("Bad-Name", "bad.", tmp_path)
    with pytest.raises(ScaffoldError, match="tool prefix"):
        new_domain("okname", "Bad Prefix", tmp_path)
    with pytest.raises(ScaffoldError, match="domain-kind"):
        new_domain("okname", "ok.", tmp_path, domain_kind="weird")


def test_cli_main_generates_and_reports(tmp_path: Path, capsys) -> None:
    assert main(["new-domain", "gadgets", "--tool-prefix", "gadgets", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "generated" in out and "gadgets" in out

    # Second run collides → loud failure, nonzero exit.
    assert main(["new-domain", "gadgets", "--tool-prefix", "gadgets", "--out", str(tmp_path)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err


def test_generated_tests_pass_as_generated(tmp_path: Path) -> None:
    _generate_inventory(tmp_path)
    new_domain("signals", "signals.", tmp_path, domain_kind="mcp")
    (tmp_path / "conftest.py").write_text(_CONFTEST_SHIM, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests", "-p", "no:cacheprovider"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"generated tests failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
