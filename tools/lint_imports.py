#!/usr/bin/env python3
"""Import-isolation linter for src/mira layer boundaries (ADR-001, ADR-007)."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path


CLOUD_PREFIXES = ("boto3", "botocore", "azure", "google.cloud")
ORCHESTRATION_PREFIXES = ("langchain", "langgraph")


@dataclass(frozen=True)
class Violation:
    path: Path
    module: str
    rule: str

    def format(self) -> str:
        return f"{self.path}: {self.module} — {self.rule}"


def _module_matches(module: str, prefix: str) -> bool:
    if prefix.endswith("*"):
        prefix = prefix[:-1]
    if prefix.endswith("."):
        return module == prefix.rstrip(".") or module.startswith(prefix)
    return module == prefix or module.startswith(f"{prefix}.")


def _is_cloud_module(module: str) -> bool:
    return any(_module_matches(module, p) for p in CLOUD_PREFIXES)


def _is_orchestration_module(module: str) -> bool:
    return any(_module_matches(module, p) for p in ORCHESTRATION_PREFIXES)


def _layer_for_path(path: Path) -> str:
    parts = path.as_posix().split("/")
    if "providers" in parts:
        return "providers"
    if "orchestration" in parts:
        return "orchestration"
    return "business"


def _iter_import_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _check_file(path: Path) -> list[Violation]:
    layer = _layer_for_path(path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Violation(path, "<syntax>", f"syntax error: {exc}")]

    violations: list[Violation] = []
    for module in _iter_import_modules(tree):
        if layer != "providers" and _is_cloud_module(module):
            violations.append(
                Violation(
                    path,
                    module,
                    "cloud SDK import allowed only under providers/",
                )
            )
        if layer != "orchestration" and _is_orchestration_module(module):
            violations.append(
                Violation(
                    path,
                    module,
                    "langchain/langgraph import allowed only under orchestration/",
                )
            )
    return violations


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def lint_paths(roots: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for root in roots:
        if not root.exists():
            sys.stderr.write(f"error: path not found: {root}\n")
            return [Violation(root, "", "path not found")]
        for path in _iter_python_files(root):
            violations.extend(_check_file(path))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="directories to scan for .py files",
    )
    args = parser.parse_args(argv)

    violations = lint_paths(args.paths)
    if not violations:
        return 0

    for violation in violations:
        print(violation.format())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
