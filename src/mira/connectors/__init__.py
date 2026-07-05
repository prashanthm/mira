"""Source connector framework — per-source adapters behind the MCP surface (ADR-020).

Connectors live in the business layer and must never import vendor SDKs; those stay
in ``providers/`` (ADR-002). Each adapter translates a source's specifics into the
uniform record shape defined in ``base`` and registers itself by source type.
"""

from mira.connectors.base import (
    ConnectorRegistry,
    Provenance,
    SourceConnector,
    SourceDescription,
    SourceRecord,
    UnknownSourceTypeError,
    registry,
)
from mira.connectors.mcp_export import (
    ToolSpec,
    ToolSpecConnector,
    export_tools,
)

__all__ = [
    "ConnectorRegistry",
    "Provenance",
    "SourceConnector",
    "SourceDescription",
    "SourceRecord",
    "ToolSpec",
    "ToolSpecConnector",
    "UnknownSourceTypeError",
    "export_tools",
    "registry",
]
