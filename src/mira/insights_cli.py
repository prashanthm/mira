"""Insight-report CLI (entry point ``mira-insights``) — ADR-006 Phase V3.

Connects to the Vantage MCP server, bridges the discovered ``vantage.*`` tools
into the advisor specialist, generates one advisory
:class:`~mira.orchestration.insights.InsightReport`, prints it as JSON to
stdout, and optionally appends it as one JSONL line to ``--out``.

Like :mod:`mira.chat` and :mod:`mira.__main__`, this is a thin app entrypoint:
the framework-touching work (tool discovery, the specialist subgraph) lives in
``orchestration`` per ADR-007 — this module imports orchestration modules but
never langchain/langgraph itself.

Exit codes: 0 on success; 1 with a clean stderr message when the MCP server is
unreachable, exposes no ``vantage.*`` tools, or the domain is unsupported.
Needs the optional ``[mcp]`` extra installed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mira.connectors.mcp_registry import McpServerSpec
from mira.orchestration.insights import generate_insight_report
from mira.orchestration.mcp_bridge import registered_tools_from_mcp
from mira.orchestration.mcp_tools import load_mcp_tools
from mira.orchestration.specialists.advisor import build_advisor_specialist

DEFAULT_MCP_URL = "http://127.0.0.1:8640/mcp"
SUPPORTED_DOMAINS = ("advisor",)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mira-insights",
        description="Generate one advisory insight report from the Vantage MCP server.",
    )
    parser.add_argument(
        "--domain",
        default="advisor",
        help=f"insight domain (supported: {', '.join(SUPPORTED_DOMAINS)}; default: advisor)",
    )
    parser.add_argument(
        "--mcp",
        default=DEFAULT_MCP_URL,
        help=f"Vantage MCP server URL (default: {DEFAULT_MCP_URL})",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="optional path to append the report to as one JSONL line",
    )
    return parser.parse_args(argv)


def _root_cause(exc: BaseException) -> str:
    """Descend ExceptionGroup/TaskGroup nesting to the most informative message."""
    current: BaseException = exc
    while True:
        nested = getattr(current, "exceptions", None)
        if nested:
            current = nested[0]
            continue
        if current.__cause__ is not None:
            current = current.__cause__
            continue
        return f"{type(current).__name__}: {current}"


def _fail(message: str) -> int:
    print(f"mira-insights: {message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.domain not in SUPPORTED_DOMAINS:
        return _fail(
            f"unsupported domain {args.domain!r} (supported: {', '.join(SUPPORTED_DOMAINS)})"
        )

    spec = McpServerSpec(name="vantage", url=args.mcp)
    try:
        discovered = load_mcp_tools([spec])
    except Exception as exc:  # noqa: BLE001 — a clean exit beats a stack trace here
        return _fail(f"cannot reach MCP server at {args.mcp} ({_root_cause(exc)})")

    vantage_tools = [
        tool
        for tool in discovered
        if str(getattr(tool, "name", "") or "").startswith("vantage.")
    ]
    if not vantage_tools:
        return _fail(f"MCP server at {args.mcp} exposes no vantage.* tools")

    specialist = build_advisor_specialist(registered_tools_from_mcp(vantage_tools))
    # same entry-point tracing pattern as the HTTP paths — a batch/CLI run mints
    # its own root trace (no inbound header) so its LLM calls are traced too.
    from mira.model import otel
    with otel.root_span("mira insights-cli", op="insights_cli"):
        report = generate_insight_report(specialist, thread_id="cli")
    payload = report.to_dict()

    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.out:
        with Path(args.out).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
