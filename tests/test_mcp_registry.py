"""Tests for the framework-free MCP server registry (config parsing only, no network)."""

from __future__ import annotations

import pytest

from mira.connectors.mcp_registry import (
    McpRegistryConfigError,
    McpServerSpec,
    load_registry,
)


def test_empty_when_nothing_declared() -> None:
    assert load_registry(environ={}) == ()


def test_mcp_base_url_shorthand_becomes_one_entry() -> None:
    registry = load_registry(environ={"MCP_BASE_URL": "http://localhost:8000/mcp"})
    assert registry == (McpServerSpec(name="default", url="http://localhost:8000/mcp"),)
    assert registry[0].transport == "streamable_http"


def test_profile_endpoint_used_when_no_env() -> None:
    registry = load_registry(profile_endpoint="http://default:8000/mcp", environ={})
    assert len(registry) == 1
    assert registry[0].url == "http://default:8000/mcp"


def test_env_overrides_profile_endpoint() -> None:
    registry = load_registry(
        profile_endpoint="http://profile/mcp",
        environ={"MCP_BASE_URL": "http://env/mcp"},
    )
    assert registry[0].url == "http://env/mcp"


def test_mcp_servers_json_multi_server() -> None:
    raw = (
        '[{"name":"default","url":"http://default/mcp","auth_token_env":"MCP_TOKEN"},'
        '{"name":"files","url":"http://files/mcp","transport":"http"}]'
    )
    registry = load_registry(environ={"MCP_SERVERS": raw})
    assert [s.name for s in registry] == ["default", "files"]
    assert registry[0].auth_token_env == "MCP_TOKEN"
    assert registry[1].transport == "http"


def test_mcp_servers_takes_precedence_over_base_url() -> None:
    registry = load_registry(
        environ={
            "MCP_SERVERS": '[{"name":"a","url":"http://a/mcp"}]',
            "MCP_BASE_URL": "http://ignored/mcp",
        }
    )
    assert [s.name for s in registry] == ["a"]


def test_invalid_json_raises() -> None:
    with pytest.raises(McpRegistryConfigError, match="not valid JSON"):
        load_registry(environ={"MCP_SERVERS": "{not json"})


def test_non_array_raises() -> None:
    with pytest.raises(McpRegistryConfigError, match="must be a JSON array"):
        load_registry(environ={"MCP_SERVERS": '{"name":"x","url":"y"}'})


def test_missing_name_raises() -> None:
    with pytest.raises(McpRegistryConfigError, match="missing a non-empty 'name'"):
        load_registry(environ={"MCP_SERVERS": '[{"url":"http://x/mcp"}]'})


def test_missing_url_raises() -> None:
    with pytest.raises(McpRegistryConfigError, match="missing a non-empty 'url'"):
        load_registry(environ={"MCP_SERVERS": '[{"name":"x"}]'})
