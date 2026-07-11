"""Shim (ADR-050): tool contracts moved to :mod:`mira_contracts.tooling`.

Re-exports only — never fork this module; new symbols land in the new home.
"""

from __future__ import annotations

from mira_contracts.tooling import (
    MAX_SCHEMA_NESTING_DEPTH,
    FlatSchemaError,
    MissingEntitlementError,
    RetryPolicy,
    ToolContract,
    ToolValidationError,
    ensure_flat_schema,
    validate_input,
)

__all__ = [
    "MAX_SCHEMA_NESTING_DEPTH",
    "FlatSchemaError",
    "MissingEntitlementError",
    "RetryPolicy",
    "ToolContract",
    "ToolValidationError",
    "ensure_flat_schema",
    "validate_input",
]
