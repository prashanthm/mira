"""Per-request attribution and MCP token relay (ADR-033)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

CORRELATION_HEADER = "X-Correlation-ID"
TENANT_HEADER = "X-Tenant-ID"
USER_HEADER = "X-User-ID"
REDACTED = "***"

# Fields that must never reach a log line or span verbatim. Attribution itself
# carries none of these, but the redaction seam guards against future additions
# and against binders that are handed extra context alongside the attribution.
SECRET_FIELDS = frozenset({"jwt", "authorization", "token", "password", "secret"})


def _normalize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def ensure_correlation_id(inbound: str | None) -> str:
    """Reuse a valid inbound correlation ID or generate a fresh UUIDv4."""
    if inbound and _is_valid_uuid(inbound.strip()):
        return inbound.strip()
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class RequestAttribution:
    """Tenant / user / correlation bound once at the request boundary."""

    tenant_id: str
    user_id: str
    correlation_id: str

    @classmethod
    def from_request(cls, headers: Mapping[str, str]) -> RequestAttribution:
        normalized = _normalize_headers(headers)
        return cls(
            tenant_id=normalized.get(TENANT_HEADER.lower(), ""),
            user_id=normalized.get(USER_HEADER.lower(), ""),
            correlation_id=ensure_correlation_id(normalized.get(CORRELATION_HEADER.lower())),
        )

    def to_log(self, *, jwt: str | None = None) -> dict[str, str]:
        payload = {key: value for key, value in asdict(self).items()}
        if jwt is not None:
            payload["jwt"] = REDACTED
        return payload

    def __repr__(self) -> str:
        return (
            f"RequestAttribution(tenant_id={self.tenant_id!r}, "
            f"user_id={self.user_id!r}, correlation_id={self.correlation_id!r})"
        )


@runtime_checkable
class MCPClient(Protocol):
    """Injectable MCP client — no real network in core."""

    def call(self, *, headers: Mapping[str, str]) -> Any: ...


def relay_to_mcp(
    client: MCPClient,
    attribution: RequestAttribution,
    jwt: str,
) -> Any:
    """Forward correlation ID and relay the caller JWT to MCP."""
    headers = {
        CORRELATION_HEADER: attribution.correlation_id,
        "Authorization": f"Bearer {jwt}",
    }
    return client.call(headers=headers)


def _redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Replace any secret-bearing field with the redaction marker."""
    return {
        key: (REDACTED if key.lower() in SECRET_FIELDS else value)
        for key, value in payload.items()
    }


def attribution_context(attribution: RequestAttribution) -> dict[str, str]:
    """The secret-redacted key/value context carried on every log line and span."""
    return _redact(asdict(attribution))


@runtime_checkable
class StructlogBinder(Protocol):
    """Injectable structlog seam — no hard structlog dependency in core.

    Mirrors ``structlog.contextvars.bind_contextvars(**kwargs)``; any object with
    that signature (including the real structlog API) satisfies the seam.
    """

    def __call__(self, **kwargs: Any) -> Any: ...


# Default in-process context, used when no concrete structlog binder is injected.
# Holds the most recently bound, redacted attribution context for the current
# execution context (request/task), so business logic never touches structlog.
_log_context: ContextVar[dict[str, str]] = ContextVar("saa_log_context", default={})


def _default_structlog_binder(**kwargs: Any) -> None:
    merged = {**_log_context.get(), **kwargs}
    _log_context.set(merged)


def get_log_context() -> dict[str, str]:
    """Return a copy of the context bound by the default structlog binder."""
    return dict(_log_context.get())


@runtime_checkable
class OtelSpan(Protocol):
    """Injectable OTel span seam — mirrors ``opentelemetry`` ``Span.set_attribute``.

    Any object exposing ``set_attribute(key, value)`` (including a real OTel span)
    satisfies the seam, so no opentelemetry SDK leaks into business logic.
    """

    def set_attribute(self, key: str, value: Any) -> Any: ...


def bind_structlog(
    attribution: RequestAttribution,
    *,
    binder: StructlogBinder | None = None,
) -> None:
    """Bind redacted tenant/user/correlation into the structlog context.

    The default binder writes into an in-process contextvar (readable via
    :func:`get_log_context`); inject the real ``structlog.contextvars.bind_contextvars``
    in production. The bound context is secret-redacted so JWTs never reach a log line.
    """
    bind = binder if binder is not None else _default_structlog_binder
    bind(**attribution_context(attribution))


def bind_otel(
    attribution: RequestAttribution,
    *,
    span: OtelSpan | None = None,
) -> None:
    """Set redacted tenant/user/correlation as OTel span attributes.

    Inject the active span (any object with ``set_attribute``); with no span this
    is a no-op so the call is safe outside a traced context.
    """
    if span is None:
        return
    for key, value in attribution_context(attribution).items():
        span.set_attribute(key, value)
