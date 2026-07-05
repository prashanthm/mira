"""Publish connector operations as typed MCP tools (ADR-020, ADR-031).

A :class:`~mira.connectors.base.SourceConnector` advertises its operations as
``capabilities`` via ``describe()``. This module turns each advertised capability
into a typed :class:`~mira.tools.contract.ToolContract`, so agents reach the source
*only* through the governed MCP surface — never via a direct connector or vendor SDK
call (ADR-020). Each emitted tool carries a flat ``inputSchema`` (ADR-031), behaviour
annotations, and a ``required_entitlement`` enforced at the inherited MCP boundary
(ADR-031 / mcp-server ADR-022).

A connector may declare richer per-operation metadata by implementing the optional
:class:`ToolSpecConnector` protocol (``tool_specs()`` returning :class:`ToolSpec`s).
A plain connector that only conforms to ``SourceConnector`` still gets safe defaults:
each capability becomes a read-only tool whose entitlement is derived from the source
type, so exposure is never silently unauthorised (the contract is fail-closed on a
missing entitlement).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from mira.connectors.base import SourceConnector
from mira.tools.contract import ToolContract

# A minimal flat object schema accepting an arbitrary request mapping. Connector
# operations take a source-specific request dict (``SourceConnector.query``); a
# connector that wants a stricter schema declares it via ``ToolSpec.input_schema``.
_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A connector's declaration of one operation to publish as an MCP tool.

    ``required_entitlement`` is mandatory and non-empty: a tool published without an
    entitlement would be fail-closed-rejected by :class:`ToolContract` anyway, so we
    surface the requirement at the connector's own declaration site.
    """

    capability: str
    required_entitlement: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_INPUT_SCHEMA))
    read_only: bool = True
    idempotent: bool = True
    destructive: bool = False
    open_world: bool = False


@runtime_checkable
class ToolSpecConnector(Protocol):
    """Optional richer protocol: a connector that declares its own per-op tool specs.

    Implementing ``tool_specs`` lets a connector set the entitlement, schema, and
    annotations for each operation explicitly, overriding the capability-derived
    defaults this module applies to plain :class:`SourceConnector`s.
    """

    def tool_specs(self) -> list[ToolSpec]:
        """Return one :class:`ToolSpec` per operation the connector exposes."""
        ...


def _entitlement_for_capability(source_type: str, capability: str) -> str:
    """Derive a default entitlement string for a capability (fail-closed default).

    Plain connectors do not declare entitlements, so we mint a deterministic,
    namespaced one (``connector:<source_type>:<capability>``) rather than leaving it
    blank — which the contract would reject.
    """
    return f"connector:{source_type}:{capability}"


def _contract_from_spec(source_type: str, spec: ToolSpec) -> ToolContract:
    return ToolContract(
        name=f"{source_type}.{spec.capability}",
        description=spec.description or f"{source_type} connector operation {spec.capability!r}",
        inputSchema=dict(spec.input_schema),
        required_entitlement=spec.required_entitlement,
        readOnlyHint=spec.read_only,
        idempotentHint=spec.idempotent,
        destructiveHint=spec.destructive,
        openWorldHint=spec.open_world,
    )


def _default_specs(connector: SourceConnector) -> list[ToolSpec]:
    """Build default :class:`ToolSpec`s from a plain connector's advertised capabilities."""
    description = connector.describe()
    source_type = description.source_type
    return [
        ToolSpec(
            capability=capability,
            required_entitlement=_entitlement_for_capability(source_type, capability),
        )
        for capability in description.capabilities
    ]


def export_tools(connector: SourceConnector) -> list[ToolContract]:
    """Publish ``connector``'s operations as typed MCP tool contracts.

    If ``connector`` implements :class:`ToolSpecConnector`, its ``tool_specs()`` drive
    publication (explicit entitlement, schema, and annotations per operation).
    Otherwise each advertised capability becomes a read-only tool with a
    capability-derived entitlement. Every returned :class:`ToolContract` carries a
    declared (non-empty) entitlement; an under-declared spec is rejected by the
    contract's fail-closed validation rather than silently exposed.
    """
    if isinstance(connector, ToolSpecConnector):
        source_type = connector.describe().source_type
        specs = connector.tool_specs()
    else:
        source_type = connector.describe().source_type
        specs = _default_specs(connector)

    return [_contract_from_spec(source_type, spec) for spec in specs]
