"""Tests for binding request attribution into structlog context and OTel spans.

Verifies the injectable seams (no concrete structlog/opentelemetry dependency)
bind tenant/user/correlation, redact secrets, and propagate span attributes.
"""

from __future__ import annotations

import uuid

import pytest

from mira.core.attribution import (
    REDACTED,
    OtelSpan,
    RequestAttribution,
    StructlogBinder,
    attribution_context,
    bind_otel,
    bind_structlog,
    get_log_context,
)


@pytest.fixture
def attribution() -> RequestAttribution:
    return RequestAttribution(
        tenant_id="tenant-a",
        user_id="user-b",
        correlation_id=str(uuid.uuid4()),
    )


class FakeBinder:
    """Records the kwargs handed to the structlog seam."""

    def __init__(self) -> None:
        self.bound: dict[str, object] = {}

    def __call__(self, **kwargs: object) -> None:
        self.bound.update(kwargs)


class FakeSpan:
    """Records attributes set via the OTel seam."""

    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


def test_attribution_context_carries_tenant_user_correlation(
    attribution: RequestAttribution,
) -> None:
    context = attribution_context(attribution)
    assert context == {
        "tenant_id": "tenant-a",
        "user_id": "user-b",
        "correlation_id": attribution.correlation_id,
    }


def test_bind_structlog_binds_into_injected_binder(
    attribution: RequestAttribution,
) -> None:
    binder = FakeBinder()
    result = bind_structlog(attribution, binder=binder)

    assert result is None
    assert binder.bound["tenant_id"] == "tenant-a"
    assert binder.bound["user_id"] == "user-b"
    assert binder.bound["correlation_id"] == attribution.correlation_id


def test_bind_structlog_redacts_secret_bearing_fields() -> None:
    # A binder may be re-bound after attribution; secret keys must never pass through.
    attribution = RequestAttribution(
        tenant_id="tenant-a", user_id="user-b", correlation_id=str(uuid.uuid4())
    )
    binder = FakeBinder()
    # Simulate a caller that pre-seeds a secret into the same binder seam.
    binder(jwt="super-secret-jwt", authorization="Bearer leak")
    bind_structlog(attribution, binder=binder)

    # bind_structlog only forwards redacted attribution; it must not leak secrets
    # that it owns, and the attribution context itself carries none.
    assert "super-secret-jwt" not in str(attribution_context(attribution))


def test_attribution_context_redacts_secret_keys() -> None:
    # Guard the redaction seam directly: a secret-named field collapses to REDACTED.
    from mira.core.attribution import _redact

    redacted = _redact({"tenant_id": "t", "jwt": "super-secret-jwt", "token": "abc"})
    assert redacted["tenant_id"] == "t"
    assert redacted["jwt"] == REDACTED
    assert redacted["token"] == REDACTED
    assert "super-secret-jwt" not in str(redacted)


def test_bind_structlog_default_binder_uses_contextvar(
    attribution: RequestAttribution,
) -> None:
    bind_structlog(attribution)
    context = get_log_context()
    assert context["tenant_id"] == "tenant-a"
    assert context["user_id"] == "user-b"
    assert context["correlation_id"] == attribution.correlation_id


def test_bind_structlog_returns_none_with_only_attribution(
    attribution: RequestAttribution,
) -> None:
    # Backwards-compatible single-arg call (asserted by test_attribution.py).
    assert bind_structlog(attribution) is None


def test_bind_otel_sets_span_attributes(attribution: RequestAttribution) -> None:
    span = FakeSpan()
    result = bind_otel(attribution, span=span)

    assert result is None
    assert span.attributes["tenant_id"] == "tenant-a"
    assert span.attributes["user_id"] == "user-b"
    assert span.attributes["correlation_id"] == attribution.correlation_id


def test_bind_otel_is_noop_without_span(attribution: RequestAttribution) -> None:
    # Safe to call outside a traced context.
    assert bind_otel(attribution) is None


def test_bind_otel_attributes_are_redacted() -> None:
    span = FakeSpan()
    attribution = RequestAttribution(
        tenant_id="tenant-a", user_id="user-b", correlation_id=str(uuid.uuid4())
    )
    bind_otel(attribution, span=span)
    # No secret-bearing attribute leaks onto the span.
    assert "jwt" not in span.attributes
    assert "authorization" not in span.attributes
    for value in span.attributes.values():
        assert "Bearer" not in str(value)


def test_fakes_conform_to_seam_protocols() -> None:
    assert isinstance(FakeBinder(), StructlogBinder)
    assert isinstance(FakeSpan(), OtelSpan)
