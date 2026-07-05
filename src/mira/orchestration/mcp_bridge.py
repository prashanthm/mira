"""MCP-discovered tools → specialist ``RegisteredTool`` bridge (ADR-014, ADR-031).

The generic primitive that turns the tools :func:`mira.orchestration.mcp_tools.
load_mcp_tools` discovers (langchain-adapter tool objects: ``.name``,
``.description``, ``.args_schema`` / ``.tool_call_schema``, ``.invoke``) into
the :class:`~mira.orchestration.specialist_scaffold.RegisteredTool` shape the
specialist scaffold binds — so a remote MCP server becomes a supervisor-routable
domain with the same allow-listing and contract validation the in-process demo
connectors get.

Contract mapping is best-effort and fail-safe:

* ``inputSchema`` — the tool's schema when it is a flat (ADR-031) object
  schema; anything unconvertible degrades to a permissive object schema rather
  than failing discovery.
* ``required_entitlement`` — ``f"{entitlement_prefix}:{tool.name}"`` so every
  bridged tool carries a non-empty entitlement (fail-closed per ADR-031).
* ``readOnlyHint`` — from the tool's metadata/annotations when the server
  declared one; otherwise ``True``: a bridged tool is presumed read-only until
  its server says otherwise, so the conservative default never *hides* a
  mutating hint that was actually sent.

Remote invocation failures raise :class:`BridgedToolError`; the scaffold's
scoped dispatcher degrades that into a structured ``{"status": "tool_error"}``
observation (fail-degraded), so a flaky server can never crash the graph.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from mira.orchestration.specialist_scaffold import DomainSpec, RegisteredTool
from mira.tools.contract import FlatSchemaError, ToolContract, ensure_flat_schema

DEFAULT_ENTITLEMENT_PREFIX = "mcp"

# Fallback when a tool's schema is absent or unconvertible: accept any object
# payload. Validation then happens server-side, which owns the real schema.
_PERMISSIVE_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}


class BridgedToolError(RuntimeError):
    """A bridged MCP tool invocation failed at the remote boundary."""


def registered_tools_from_mcp(
    tools: Sequence[Any],
    *,
    entitlement_prefix: str = DEFAULT_ENTITLEMENT_PREFIX,
) -> list[RegisteredTool]:
    """Wrap MCP-discovered langchain tools as scaffold-bindable registered tools."""
    return [_bridge_tool(tool, entitlement_prefix=entitlement_prefix) for tool in tools]


def domain_spec_for_server(server_name: str, tools: Sequence[Any]) -> DomainSpec:
    """Build the :class:`DomainSpec` scoping a specialist to one MCP server's tools.

    Servers namespace their tools ``"<server>.<tool>"`` (e.g.
    ``"vantage.positions"``), so the canonical allow-list is the single prefix
    ``f"{server_name}."``. When the discovered tool names do not all carry that
    namespace, fall back to the prefixes actually observed so the allow-list
    still covers exactly this server's tool surface.
    """
    canonical = f"{server_name}."
    names = [str(getattr(tool, "name", "") or "") for tool in tools]
    if names and all(name.startswith(canonical) for name in names):
        return DomainSpec(domain_id=server_name, tool_prefixes=frozenset({canonical}))

    prefixes: set[str] = set()
    for name in names:
        head, sep, _rest = name.partition(".")
        prefixes.add(f"{head}." if sep else name)
    prefixes.discard("")
    return DomainSpec(
        domain_id=server_name,
        tool_prefixes=frozenset(prefixes) if prefixes else frozenset({canonical}),
    )


def _bridge_tool(tool: Any, *, entitlement_prefix: str) -> RegisteredTool:
    name = str(getattr(tool, "name", "") or "")
    contract = ToolContract(
        name=name,
        description=str(getattr(tool, "description", "") or ""),
        inputSchema=_flat_input_schema(tool),
        required_entitlement=f"{entitlement_prefix}:{name}",
        readOnlyHint=_read_only_hint(tool),
    )

    def handler(payload: dict[str, Any]) -> Any:
        try:
            raw = tool.invoke(payload)
        except Exception as exc:
            raise BridgedToolError(
                f"MCP tool {name!r} invocation failed: {type(exc).__name__}: {exc}"
            ) from exc
        return _json_safe_result(raw)

    return RegisteredTool(contract=contract, handler=handler)


def _flat_input_schema(tool: Any) -> dict[str, Any]:
    """Best-effort flat (ADR-031) object schema for the tool's declared input.

    Accepts a plain-dict schema or a pydantic model class (via
    ``model_json_schema``); anything else — or a schema that is not a flat
    object — degrades to the permissive object schema.
    """
    declared = getattr(tool, "args_schema", None)
    if declared is None:
        declared = getattr(tool, "tool_call_schema", None)

    schema: Any = declared
    if schema is not None and not isinstance(schema, Mapping):
        to_json_schema = getattr(schema, "model_json_schema", None)
        if callable(to_json_schema):
            try:
                schema = to_json_schema()
            except Exception:  # noqa: BLE001 — degrade, never fail discovery
                schema = None
        else:
            schema = None

    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        return dict(_PERMISSIVE_SCHEMA)

    candidate = dict(schema)
    try:
        ensure_flat_schema(candidate)
    except FlatSchemaError:
        return dict(_PERMISSIVE_SCHEMA)
    return candidate


def _read_only_hint(tool: Any) -> bool:
    """Read the MCP ``readOnlyHint`` from tool metadata/annotations when present.

    Defaults to ``True`` when the server sent no annotation: bridged tools are
    presumed read-only rather than silently gaining write posture — a mutating
    tool must declare itself (``readOnlyHint: false``) to be treated as one.
    """
    candidates: list[Any] = []
    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, Mapping):
        candidates.append(metadata.get("readOnlyHint"))
        annotations = metadata.get("annotations")
        if isinstance(annotations, Mapping):
            candidates.append(annotations.get("readOnlyHint"))
    annotations_attr = getattr(tool, "annotations", None)
    if isinstance(annotations_attr, Mapping):
        candidates.append(annotations_attr.get("readOnlyHint"))
    elif annotations_attr is not None:
        candidates.append(getattr(annotations_attr, "readOnlyHint", None))

    for value in candidates:
        if isinstance(value, bool):
            return value
    return True


def _json_safe_result(raw: Any) -> Any:
    """Normalize a tool result to JSON-safe data the scaffold can serialize.

    MCP text content frequently *is* JSON — parse strings back into structures
    when possible; wrap any non-dict result as ``{"result": ...}`` so specialist
    answers stay object-shaped.
    """
    value: Any = raw
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = text
    if isinstance(value, Mapping):
        return dict(value)
    return {"result": value}


__all__ = [
    "BridgedToolError",
    "DEFAULT_ENTITLEMENT_PREFIX",
    "domain_spec_for_server",
    "registered_tools_from_mcp",
]
