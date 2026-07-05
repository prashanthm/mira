import inspect

import pytest

from mira.tools.authz import entitlement_for
from mira.tools.contract import MissingEntitlementError, ToolContract


def _flat_contract(**overrides) -> ToolContract:
    defaults = {
        "name": "get_well",
        "description": "Fetch well metadata by id",
        "inputSchema": {
            "type": "object",
            "properties": {"well_id": {"type": "string"}},
            "required": ["well_id"],
        },
        "required_entitlement": "users.datalake.viewers@partition.dataservices.energy",
    }
    defaults.update(overrides)
    return ToolContract(**defaults)


def test_entitlement_for_surfaces_declared_entitlement():
    contract = _flat_contract(
        required_entitlement="users.datalake.editors@partition.dataservices.energy"
    )
    assert (
        entitlement_for(contract)
        == "users.datalake.editors@partition.dataservices.energy"
    )


def test_contract_without_required_entitlement_is_rejected():
    # Omitted entitlement is fail-closed with the SAME structured error as a
    # blank value (unified on MissingEntitlementError, not dataclass TypeError).
    with pytest.raises(MissingEntitlementError) as exc_info:
        ToolContract(
            name="missing_authz",
            description="no entitlement field",
            inputSchema={"type": "object", "properties": {}},
        )
    assert "required_entitlement" in exc_info.value.message


def test_contract_with_blank_entitlement_is_rejected_fail_closed():
    with pytest.raises(MissingEntitlementError) as exc_info:
        _flat_contract(required_entitlement="   ")
    assert "required_entitlement" in exc_info.value.message
    assert exc_info.value.details


def test_authz_module_only_surfaces_entitlement_no_local_enforcement():
    public = {
        name: obj
        for name, obj in inspect.getmembers(inspect.getmodule(entitlement_for))
        if not name.startswith("_") and inspect.isfunction(obj)
    }
    assert set(public) == {"entitlement_for"}
