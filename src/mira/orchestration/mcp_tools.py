"""Discover MCP server tools as LangChain tools (ADR-007 orchestration boundary).

This is the *only* place the langchain MCP adapter is imported — ADR-007 contains
langchain/langgraph to ``orchestration/`` (enforced by ``tools/lint_imports.py`` and
``test_no_langgraph_import_outside_orchestration``). It consumes the framework-free
:class:`~mira.connectors.mcp_registry.McpServerSpec` registry, builds a
``MultiServerMCPClient`` over Streamable HTTP, and returns the merged LangChain tools
ready for ``bind_tools()`` and for the runtime to execute.

Tool discovery is async (``client.get_tools()``); it runs **once at app-build time** via
:func:`load_mcp_tools`, which bridges to sync with ``asyncio.run`` so the synchronous
``AgentRuntime`` need not become async on the hot path. Per-call attribution headers
(correlation id + bearer) are built the same way as
:func:`mira.core.attribution.relay_to_mcp` — the constant is reused, not duplicated.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from typing import Any

from mira.connectors.mcp_registry import McpServerSpec
from mira.core.attribution import CORRELATION_HEADER, RequestAttribution


def _headers_for(spec: McpServerSpec, attribution: RequestAttribution | None) -> dict[str, str]:
    """Build the per-server request headers: correlation id + optional bearer token.

    Mirrors :func:`mira.core.attribution.relay_to_mcp` (reusing ``CORRELATION_HEADER`` and
    the ``Authorization: Bearer`` convention). The token is read from the env var named by
    ``spec.auth_token_env`` at connect time, so it never lives in the registry or a log.
    A server with no token env (e.g. MCP server local ``SKIP_AUTH``) sends no auth header.
    """
    headers: dict[str, str] = {}
    if attribution is not None and attribution.correlation_id:
        headers[CORRELATION_HEADER] = attribution.correlation_id
    if spec.auth_token_env:
        token = os.environ.get(spec.auth_token_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def _connections(
    registry: Sequence[McpServerSpec],
    attribution: RequestAttribution | None,
) -> dict[str, dict[str, Any]]:
    """Map the declared registry to a ``MultiServerMCPClient`` connections dict."""
    connections: dict[str, dict[str, Any]] = {}
    for spec in registry:
        conn: dict[str, Any] = {"transport": spec.transport, "url": spec.url}
        headers = _headers_for(spec, attribution)
        if headers:
            conn["headers"] = headers
        connections[spec.name] = conn
    return connections


async def _discover(connections: Mapping[str, dict[str, Any]]) -> list[Any]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(dict(connections))
    return await client.get_tools()


def to_openai_specs(tools: Sequence[Any]) -> list[dict[str, Any]]:
    """Convert discovered LangChain tools to OpenAI function specs (orchestration boundary).

    Keeps the langchain conversion inside ``orchestration/`` (ADR-007) so callers — a chat
    harness, the runtime — get plain dict specs without importing langchain themselves.
    """
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return [convert_to_openai_tool(tool) for tool in tools]


def load_mcp_tools(
    registry: Sequence[McpServerSpec],
    *,
    attribution: RequestAttribution | None = None,
) -> list[Any]:
    """Discover MCP tools synchronously (app-build-time, one-shot).

    Thin ``asyncio.run`` wrapper over :func:`aload_mcp_tools` for the synchronous
    composition path (``build_app``). **Must not be called from within a running event
    loop** — ``asyncio.run`` would raise; an async caller (e.g. a chatbot harness) should
    await :func:`aload_mcp_tools` directly. Empty registry → empty list.
    """
    if not registry:
        return []
    return asyncio.run(aload_mcp_tools(registry, attribution=attribution))


async def aload_mcp_tools(
    registry: Sequence[McpServerSpec],
    *,
    attribution: RequestAttribution | None = None,
) -> list[Any]:
    """Async discovery of the merged LangChain tools for a declared MCP registry.

    Empty registry → empty list. Raises a clear ``ImportError`` if the optional ``[mcp]``
    extra is not installed. Use this from code already inside an event loop; the sync
    :func:`load_mcp_tools` wraps it for the synchronous app-build path.
    """
    if not registry:
        return []
    try:
        connections = _connections(registry, attribution)
        return await _discover(connections)
    except ImportError as exc:  # pragma: no cover - only without the [mcp] extra
        raise ImportError(
            "langchain-mcp-adapters and mcp are required to load MCP tools; install the "
            "optional extra: pip install '.[mcp]'"
        ) from exc
