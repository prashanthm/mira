"""Tests for request attribution and MCP token relay."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

from mira.core.attribution import (
    CORRELATION_HEADER,
    TENANT_HEADER,
    USER_HEADER,
    MCPClient,
    RequestAttribution,
    bind_otel,
    bind_structlog,
    ensure_correlation_id,
    relay_to_mcp,
)


class FakeMCPClient:
    def __init__(self) -> None:
        self.last_headers: dict[str, str] | None = None

    def call(self, *, headers: dict[str, str]) -> str:
        self.last_headers = dict(headers)
        return "ok"


def test_from_request_binds_tenant_user_correlation_once() -> None:
    correlation = str(uuid.uuid4())
    headers = {
        TENANT_HEADER: "tenant-a",
        USER_HEADER: "user-b",
        CORRELATION_HEADER: correlation,
    }
    attribution = RequestAttribution.from_request(headers)

    assert attribution.tenant_id == "tenant-a"
    assert attribution.user_id == "user-b"
    assert attribution.correlation_id == correlation

    with pytest.raises(FrozenInstanceError):
        attribution.correlation_id = "mutated"  # type: ignore[misc]


def test_ensure_correlation_id_reuses_valid_inbound() -> None:
    correlation = str(uuid.uuid4())
    assert ensure_correlation_id(correlation) == correlation


@pytest.mark.parametrize("invalid", ["", "not-a-uuid", "12345", None])
def test_ensure_correlation_id_generates_when_missing_or_invalid(invalid: str | None) -> None:
    generated = ensure_correlation_id(invalid)
    uuid.UUID(generated)


def test_from_request_generates_correlation_when_absent() -> None:
    attribution = RequestAttribution.from_request(
        {TENANT_HEADER: "tenant-a", USER_HEADER: "user-b"}
    )
    uuid.UUID(attribution.correlation_id)


def test_relay_forwards_correlation_and_relays_jwt() -> None:
    correlation = str(uuid.uuid4())
    attribution = RequestAttribution(
        tenant_id="tenant-a",
        user_id="user-b",
        correlation_id=correlation,
    )
    client = FakeMCPClient()
    token = "eyJ.test.token"

    assert relay_to_mcp(client, attribution, token) == "ok"
    assert client.last_headers is not None
    assert client.last_headers[CORRELATION_HEADER] == correlation
    assert client.last_headers["Authorization"] == f"Bearer {token}"


def test_relay_does_not_regenerate_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    correlation = str(uuid.uuid4())
    attribution = RequestAttribution(
        tenant_id="tenant-a",
        user_id="user-b",
        correlation_id=correlation,
    )
    client = FakeMCPClient()

    def fail_uuid4() -> uuid.UUID:
        raise AssertionError("correlation ID must be forwarded, not regenerated")

    monkeypatch.setattr("mira.core.attribution.uuid.uuid4", fail_uuid4)
    relay_to_mcp(client, attribution, "token")
    assert client.last_headers is not None
    assert client.last_headers[CORRELATION_HEADER] == correlation


def test_to_log_redacts_jwt() -> None:
    attribution = RequestAttribution(
        tenant_id="tenant-a",
        user_id="user-b",
        correlation_id=str(uuid.uuid4()),
    )
    payload = attribution.to_log(jwt="super-secret-jwt")

    assert payload["jwt"] == "***"
    assert "super-secret-jwt" not in str(payload)


def test_repr_never_includes_jwt() -> None:
    attribution = RequestAttribution(
        tenant_id="tenant-a",
        user_id="user-b",
        correlation_id=str(uuid.uuid4()),
    )
    text = repr(attribution)
    assert "jwt" not in text.lower()
    assert "Bearer" not in text


def test_mcp_client_protocol_conformance() -> None:
    assert isinstance(FakeMCPClient(), MCPClient)


@pytest.mark.parametrize(
    "tenant_key, user_key, corr_key",
    [
        ("x-tenant-id", "x-user-id", "x-correlation-id"),
        ("X-TENANT-ID", "X-USER-ID", "X-CORRELATION-ID"),
        ("X-Tenant-Id", "X-User-Id", "X-Correlation-Id"),
    ],
)
def test_from_request_is_case_insensitive(tenant_key, user_key, corr_key) -> None:
    correlation = str(uuid.uuid4())
    attribution = RequestAttribution.from_request(
        {tenant_key: "tenant-a", user_key: "user-b", corr_key: correlation}
    )
    assert attribution.tenant_id == "tenant-a"
    assert attribution.user_id == "user-b"
    assert attribution.correlation_id == correlation


def test_observability_binding_stubs_are_callable() -> None:
    # L2: guard against accidental removal of the stub hooks.
    attribution = RequestAttribution(
        tenant_id="t", user_id="u", correlation_id=str(uuid.uuid4())
    )
    assert bind_structlog(attribution) is None
    assert bind_otel(attribution) is None
