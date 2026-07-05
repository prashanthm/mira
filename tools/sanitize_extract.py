#!/usr/bin/env python3
"""One-shot extraction sanitizer used to derive Mira from its upstream codebase.

Kept in-repo as provenance: it documents exactly which mechanical renames and
string substitutions produced the initial Mira tree. It is idempotent — running
it against an already-sanitized tree is a no-op. The `make sanitize-check`
target (grep gate) is the permanent guard; this script is the historical record
of the transformation.

Order matters: longer/more-specific tokens are replaced before shorter ones so
word-boundary passes never mangle compound names (e.g. ``edi-saas`` must become
``saas`` before ``\bsaa\b`` -> ``mira`` runs, and must itself run before
``\bedi\b`` is rewritten).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".py", ".toml", ".md", ".yml", ".yaml", ".tf", ".json", ".txt",
    ".cfg", ".ini", ".sh", "", ".tpl",
}
SKIP_NAMES = {"sanitize_extract.py"}
# Rewritten wholesale afterwards; the mechanical pass must not touch them.
SKIP_REWRITE = {"README.md", "AGENTS.md"}

# (pattern, replacement) applied in order to every text file.
REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # -- org / repo identity -------------------------------------------------
    (re.compile(r"subsurface-agentic-ai"), "mira"),
    (re.compile(r"47lining"), "prashanthm"),
    # -- compound domain tokens (before their shorter roots) ------------------
    (re.compile(r"edi-saas"), "saas"),
    (re.compile(r"EDI_TOKEN"), "MCP_TOKEN"),
    (re.compile(r"edi-mcp ADR"), "mcp-server ADR"),
    (re.compile(r"Subsurface Agentic AI"), "Mira"),
    (re.compile(r"subsurface agent service"), "Mira agent service"),
    (re.compile(r"osdu_search"), "catalog_search"),
    (re.compile(r"osdu:"), "catalog:"),
    # -- package rename --------------------------------------------------------
    (re.compile(r"\bsaa\b"), "mira"),
    # -- residual domain vocabulary -------------------------------------------
    (re.compile(r"\bosdu\b"), "catalog"),
    (re.compile(r"\bOSDU\b"), "Catalog"),
    (re.compile(r"\bedi\b"), "default"),
    (re.compile(r"\bEDI\b"), "MCP server"),
    (re.compile(r"\bsubsurface\b"), "Mira"),
    # cosmetic cleanups produced by the passes above
    (re.compile(r"Catalog catalogue"), "catalog"),
    (re.compile(r"\$MCP_TOKEN / \$MCP_TOKEN"), "$MCP_TOKEN"),
]


def sanitize_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    for pattern, repl in REPLACEMENTS:
        text = pattern.sub(repl, text)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main(root: Path) -> int:
    changed = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES or path.name in SKIP_REWRITE:
            continue
        if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            if sanitize_file(path):
                changed += 1
                print(f"sanitized: {path.relative_to(root)}")
        except UnicodeDecodeError:
            continue
    print(f"\n{changed} files changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
