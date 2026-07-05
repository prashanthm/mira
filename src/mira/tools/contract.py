"""Typed MCP tool contracts (ADR-031)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

MAX_SCHEMA_NESTING_DEPTH = 2


class ToolValidationError(Exception):
    """Structured error when tool input fails contract validation."""

    def __init__(self, message: str, *, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class FlatSchemaError(ToolValidationError):
    """Raised when a schema exceeds allowed nesting depth."""


class MissingEntitlementError(ToolValidationError):
    """Raised when a tool contract omits required_entitlement (fail-closed)."""


def _schema_nesting_depth(node: Any, depth: int = 0) -> int:
    if not isinstance(node, dict):
        return depth

    max_depth = depth
    node_type = node.get("type")

    if node_type == "object" and isinstance(node.get("properties"), dict):
        for prop_schema in node["properties"].values():
            max_depth = max(max_depth, _schema_nesting_depth(prop_schema, depth + 1))
    elif node_type == "array" and "items" in node:
        max_depth = max(max_depth, _schema_nesting_depth(node["items"], depth + 1))

    for combiner in ("oneOf", "anyOf", "allOf"):
        variants = node.get(combiner)
        if isinstance(variants, list):
            for variant in variants:
                max_depth = max(max_depth, _schema_nesting_depth(variant, depth))

    return max_depth


def ensure_flat_schema(schema: dict[str, Any], *, label: str = "inputSchema") -> None:
    """Reject a deeply nested schema per ADR-031 flat-schema guidance.

    Applied to both ``inputSchema`` and (when present) ``outputSchema``.
    """
    if _schema_nesting_depth(schema) > MAX_SCHEMA_NESTING_DEPTH:
        raise FlatSchemaError(
            f"{label} nesting depth exceeds {MAX_SCHEMA_NESTING_DEPTH}",
            details=[f"max_allowed_depth={MAX_SCHEMA_NESTING_DEPTH}"],
        )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Per-tool retry semantics: retryable error classes and backoff."""

    retryable_exceptions: tuple[type[BaseException], ...]
    max_attempts: int = 3
    backoff_s: float = 0.0


@dataclass(frozen=True, slots=True)
class ToolContract:
    """MCP tool contract: schema, annotations, and validation metadata."""

    name: str
    description: str
    inputSchema: dict[str, Any]
    # Default "" so an omitted entitlement flows through __post_init__ and raises
    # MissingEntitlementError (fail-closed) — a single error type for both the
    # omitted and blank cases, rather than dataclass TypeError vs the structured
    # error.
    required_entitlement: str = ""
    readOnlyHint: bool = False
    idempotentHint: bool = False
    destructiveHint: bool = False
    openWorldHint: bool = False
    outputSchema: dict[str, Any] | None = None
    timeout_s: float | None = None
    retry_policy: RetryPolicy | None = None

    def __post_init__(self) -> None:
        ensure_flat_schema(self.inputSchema, label="inputSchema")
        if self.outputSchema is not None:
            ensure_flat_schema(self.outputSchema, label="outputSchema")
        if not self.required_entitlement or not self.required_entitlement.strip():
            raise MissingEntitlementError(
                f"Tool contract {self.name!r} must declare required_entitlement",
                details=["fail_closed=true"],
            )

    @property
    def idempotent(self) -> bool:
        """Whether safe retries/dedup are allowed (MCP idempotentHint)."""
        return self.idempotentHint


def validate_input(contract: ToolContract, payload: dict[str, Any]) -> None:
    """Validate payload against contract.inputSchema; raise ToolValidationError on mismatch."""
    try:
        # Explicit validator class for forward compatibility (L1).
        Draft202012Validator(contract.inputSchema).validate(payload)
    except JsonSchemaValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ToolValidationError(
            f"Invalid input for tool {contract.name!r} at {path}: {exc.message}",
            details=[str(exc.validator), str(exc.validator_value)],
        ) from exc
