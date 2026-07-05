import pytest

from mira.tools.contract import (
    FlatSchemaError,
    ToolContract,
    ToolValidationError,
    validate_input,
)


def _flat_contract(**overrides) -> ToolContract:
    defaults = {
        "name": "get_well",
        "description": "Fetch well metadata by id",
        "inputSchema": {
            "type": "object",
            "properties": {
                "well_id": {"type": "string"},
                "include_logs": {"type": "boolean"},
            },
            "required": ["well_id"],
            "additionalProperties": False,
        },
        "required_entitlement": "users.datalake.viewers@partition.dataservices.energy",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
        "outputSchema": {"type": "object", "properties": {"name": {"type": "string"}}},
    }
    defaults.update(overrides)
    return ToolContract(**defaults)


def test_valid_contract_carries_mcp_annotations():
    contract = _flat_contract()
    assert contract.name == "get_well"
    assert contract.readOnlyHint is True
    assert contract.idempotentHint is True
    assert contract.destructiveHint is False
    assert contract.openWorldHint is False
    assert contract.outputSchema is not None


def test_validate_input_accepts_valid_payload():
    contract = _flat_contract()
    validate_input(contract, {"well_id": "W-1", "include_logs": True})


def test_validate_input_rejects_malformed_payload():
    contract = _flat_contract()
    with pytest.raises(ToolValidationError) as exc_info:
        validate_input(contract, {"include_logs": True})
    assert "well_id" in exc_info.value.message or "required" in exc_info.value.message.lower()
    assert exc_info.value.details


def test_flat_schema_rejects_deeply_nested_input_schema():
    deep_schema = {
        "type": "object",
        "properties": {
            "outer": {
                "type": "object",
                "properties": {
                    "middle": {
                        "type": "object",
                        "properties": {"inner": {"type": "string"}},
                    }
                },
            }
        },
    }
    with pytest.raises(FlatSchemaError):
        ToolContract(
            name="deep_tool",
            description="too nested",
            inputSchema=deep_schema,
            required_entitlement="users.datalake.viewers@partition.dataservices.energy",
        )


def test_deeply_nested_output_schema_is_rejected():
    # M1: the flat-schema guard must apply to outputSchema, not only inputSchema.
    deep_output = {
        "type": "object",
        "properties": {
            "result": {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {"inner": {"type": "string"}},
                    }
                },
            }
        },
    }
    with pytest.raises(FlatSchemaError, match="outputSchema"):
        ToolContract(
            name="deep_out",
            description="too nested output",
            inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
            outputSchema=deep_output,
        )


def test_one_level_nested_object_is_allowed():
    contract = ToolContract(
        name="nested_once",
        description="one nested object",
        inputSchema={
            "type": "object",
            "properties": {
                "location": {
                    "type": "object",
                    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                }
            },
        },
        required_entitlement="users.datalake.viewers@partition.dataservices.energy",
    )
    validate_input(contract, {"location": {"x": 1.0, "y": 2.0}})
