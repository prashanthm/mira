"""Declared MCP server registry — framework-free config (ADR-007, ADR-020).

MCP has no server auto-discovery: clients are always configured with an explicit list of
servers (the ``mcpServers`` map pattern in Claude Desktop / Cursor / VS Code), and discover
*tools within* a server dynamically via ``list_tools()``. This module models that declared
registry — parsing the ``MCP_SERVERS`` env config and building per-server connection specs
(url + transport + auth headers) — **without importing any framework**. The langchain
``MultiServerMCPClient`` that consumes a spec lives in ``orchestration/`` (ADR-007), so this
stays a plain-data boundary.

Config precedence (resolved in :func:`load_registry`):

* ``MCP_SERVERS`` — a JSON array of ``{name, url, transport?, auth_token_env?}`` objects,
  the multi-server form.
* ``MCP_BASE_URL`` — back-compat shorthand for a single ``default`` server, so existing
  single-endpoint config keeps working as a one-entry registry.
* a ``Profile.mcp_endpoint`` default passed in — same shorthand, profile-supplied.

An empty registry (no env, no profile default) is the zero-MCP-tools case: the agent runs
exactly as before.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

MCP_SERVERS_ENV = "MCP_SERVERS"
MCP_BASE_URL_ENV = "MCP_BASE_URL"

# Default name for the single-endpoint shorthand (MCP_BASE_URL / profile.mcp_endpoint).
_DEFAULT_SERVER_NAME = "default"
# Streamable HTTP is the MCP server server's transport; the langchain adapter accepts this alias.
_DEFAULT_TRANSPORT = "streamable_http"


class McpRegistryConfigError(ValueError):
    """Raised when ``MCP_SERVERS`` is present but not a valid server list."""


@dataclass(frozen=True, slots=True)
class McpServerSpec:
    """One declared MCP server: a name + URL + transport + optional bearer-token env key.

    ``auth_token_env`` names the env var holding this server's bearer token (resolved at
    connect time, never stored here), so a token never lives in the spec or a log line. A
    server with no ``auth_token_env`` is unauthenticated (e.g. MCP server local ``SKIP_AUTH``).
    """

    name: str
    url: str
    transport: str = _DEFAULT_TRANSPORT
    auth_token_env: str | None = None


def _spec_from_mapping(entry: object, index: int) -> McpServerSpec:
    if not isinstance(entry, dict):
        raise McpRegistryConfigError(
            f"{MCP_SERVERS_ENV}[{index}] must be an object, got {type(entry).__name__}"
        )
    name = entry.get("name")
    url = entry.get("url")
    if not isinstance(name, str) or not name:
        raise McpRegistryConfigError(f"{MCP_SERVERS_ENV}[{index}] is missing a non-empty 'name'")
    if not isinstance(url, str) or not url:
        raise McpRegistryConfigError(f"{MCP_SERVERS_ENV}[{index}] is missing a non-empty 'url'")
    transport = entry.get("transport", _DEFAULT_TRANSPORT)
    if not isinstance(transport, str) or not transport:
        raise McpRegistryConfigError(f"{MCP_SERVERS_ENV}[{index}] has an invalid 'transport'")
    auth_token_env = entry.get("auth_token_env")
    if auth_token_env is not None and not isinstance(auth_token_env, str):
        raise McpRegistryConfigError(f"{MCP_SERVERS_ENV}[{index}] 'auth_token_env' must be a string")
    return McpServerSpec(name=name, url=url, transport=transport, auth_token_env=auth_token_env)


def _parse_servers_env(raw: str) -> list[McpServerSpec]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise McpRegistryConfigError(f"{MCP_SERVERS_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise McpRegistryConfigError(f"{MCP_SERVERS_ENV} must be a JSON array of server objects")
    return [_spec_from_mapping(entry, i) for i, entry in enumerate(parsed)]


def load_registry(
    *,
    profile_endpoint: str | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[McpServerSpec, ...]:
    """Resolve the declared MCP server registry (env first, then profile shorthand).

    Returns an empty tuple when nothing is declared (zero-MCP-tools, unchanged behavior).
    ``environ`` defaults to ``os.environ``; pass an explicit mapping in tests.
    """
    env = environ if environ is not None else dict(os.environ)

    servers_raw = env.get(MCP_SERVERS_ENV)
    if servers_raw and servers_raw.strip():
        return tuple(_parse_servers_env(servers_raw))

    single_url = env.get(MCP_BASE_URL_ENV) or profile_endpoint
    if single_url:
        return (McpServerSpec(name=_DEFAULT_SERVER_NAME, url=single_url),)

    return ()
