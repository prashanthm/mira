"""Tests for MCP tool discovery wiring (header/connection mapping; no network).

The langchain adapter import is confined to ``_discover``/``load_mcp_tools``; the header
and connection builders are framework-free and tested directly. ``load_mcp_tools`` with an
empty registry must short-circuit to ``[]`` without importing the adapter.
"""

from __future__ import annotations

from mira.connectors.mcp_registry import McpServerSpec
from mira.core.attribution import CORRELATION_HEADER, RequestAttribution
from mira.orchestration.mcp_tools import _connections, _headers_for, load_mcp_tools


def _attr(correlation_id: str = "11111111-1111-4111-8111-111111111111") -> RequestAttribution:
    return RequestAttribution(tenant_id="t", user_id="u", correlation_id=correlation_id)


def test_headers_include_correlation_id() -> None:
    spec = McpServerSpec(name="default", url="http://default/mcp")
    headers = _headers_for(spec, _attr())
    assert headers[CORRELATION_HEADER] == "11111111-1111-4111-8111-111111111111"
    assert "Authorization" not in headers  # no token env → no auth header


def test_headers_include_bearer_from_token_env(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TOKEN", "secret-jwt")
    spec = McpServerSpec(name="default", url="http://default/mcp", auth_token_env="MCP_TOKEN")
    headers = _headers_for(spec, _attr())
    assert headers["Authorization"] == "Bearer secret-jwt"


def test_headers_skip_bearer_when_token_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    spec = McpServerSpec(name="default", url="http://default/mcp", auth_token_env="MCP_TOKEN")
    headers = _headers_for(spec, _attr())
    assert "Authorization" not in headers


def test_headers_without_attribution() -> None:
    spec = McpServerSpec(name="default", url="http://default/mcp")
    assert _headers_for(spec, None) == {}


def test_connections_map_shape() -> None:
    registry = [
        McpServerSpec(name="default", url="http://default/mcp"),
        McpServerSpec(name="files", url="http://files/mcp", transport="http"),
    ]
    conns = _connections(registry, _attr())
    assert conns["default"]["transport"] == "streamable_http"
    assert conns["default"]["url"] == "http://default/mcp"
    assert conns["default"]["headers"][CORRELATION_HEADER]
    assert conns["files"]["transport"] == "http"


def test_load_mcp_tools_empty_registry_is_noop() -> None:
    # Empty registry must not import the adapter — returns [] directly.
    assert load_mcp_tools([]) == []


def test_aload_mcp_tools_empty_registry_is_noop() -> None:
    # Async discovery path (for callers already in an event loop) short-circuits too.
    import asyncio

    from mira.orchestration.mcp_tools import aload_mcp_tools

    assert asyncio.run(aload_mcp_tools([])) == []
