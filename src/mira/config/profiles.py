"""Deployment profile loader (ADR-047)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Mapping

PROFILE_ENV = "DEPLOYMENT_PROFILE"

# NOTE: this loader uses `kubernetes` as the Mira alias for ADR-047's
# `customer-k8s` profile. Downstream Helm values and ADR startup logging must
# resolve to this single canonical name; reconcile via an ADR amendment if the
# names are unified later (tracked as M2 follow-up on #53).
KNOWN_PROFILES = frozenset({"local", "saas", "standalone", "kubernetes", "outposts"})


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    """Observability defaults resolved from profile and env."""

    otlp_endpoint: str | None
    log_level: str


@dataclass(frozen=True, slots=True)
class Profile:
    """Resolved deployment profile configuration."""

    name: str
    platform: str
    auth_mode: str
    mcp_endpoint: str | None
    region: str
    flags: Mapping[str, bool] = field(default_factory=dict)
    observability: ObservabilityConfig = field(
        default_factory=lambda: ObservabilityConfig(otlp_endpoint=None, log_level="info")
    )


_PROFILE_DEFAULTS: dict[str, Profile] = {
    # A profile is a named *default-set* for the independent axes (platform / model /
    # mcp_endpoint / auth_mode), each still overridable by env (ADR-047). `local` is the
    # dev shape: local infra bundle + skip-auth + localhost MCP server as the MCP endpoint. The
    # model is a separate axis — point LLM_BASE_URL at Ollama (local) or a LiteLLM proxy
    # (Bedrock) without changing the profile.
    "local": Profile(
        name="local",
        platform="local",
        auth_mode="skip",
        mcp_endpoint="http://localhost:8000/mcp",
        region="local",
        flags={"multi_tenant": False},
        observability=ObservabilityConfig(otlp_endpoint=None, log_level="debug"),
    ),
    "saas": Profile(
        name="saas",
        platform="aws",
        auth_mode="gateway-injected-tenant",
        mcp_endpoint=None,
        region="us-east-1",
        flags={"multi_tenant": True},
        observability=ObservabilityConfig(otlp_endpoint=None, log_level="info"),
    ),
    "standalone": Profile(
        name="standalone",
        platform="aws",
        auth_mode="customer-idp",
        mcp_endpoint=None,
        region="us-east-1",
        flags={"multi_tenant": False},
        observability=ObservabilityConfig(otlp_endpoint=None, log_level="info"),
    ),
    "kubernetes": Profile(
        name="kubernetes",
        platform="aws",
        auth_mode="customer-idp",
        mcp_endpoint=None,
        region="us-east-1",
        flags={"multi_tenant": False},
        observability=ObservabilityConfig(otlp_endpoint=None, log_level="info"),
    ),
    "outposts": Profile(
        name="outposts",
        platform="aws",
        auth_mode="customer-idp",
        mcp_endpoint=None,
        region="us-east-1",
        flags={"degraded_mode": True},
        observability=ObservabilityConfig(otlp_endpoint=None, log_level="info"),
    ),
}


def _apply_env_overrides(base: Profile) -> Profile:
    """Apply explicit env overrides over profile defaults (ADR-047)."""
    platform = os.environ.get("PLATFORM", base.platform)
    auth_mode = os.environ.get("AUTH_MODE", base.auth_mode)
    mcp_endpoint = os.environ.get("MCP_BASE_URL", base.mcp_endpoint)
    region = os.environ.get("AWS_REGION", base.region)

    # ADR-047 treats ENABLE_* as feature-flag toggles over the profile's
    # semantic flag keys. Strip the prefix and lowercase so ENABLE_MULTI_TENANT
    # overrides the `multi_tenant` default rather than adding a parallel
    # `ENABLE_MULTI_TENANT` key with a divergent naming scheme.
    flags: dict[str, bool] = dict(base.flags)
    for key, value in os.environ.items():
        if key.startswith("ENABLE_"):
            flag_name = key[len("ENABLE_"):].lower()
            flags[flag_name] = value.lower() in ("1", "true", "yes", "on")

    otlp_endpoint = os.environ.get("OTLP_ENDPOINT", base.observability.otlp_endpoint)
    log_level = os.environ.get("LOG_LEVEL", base.observability.log_level)
    observability = ObservabilityConfig(otlp_endpoint=otlp_endpoint, log_level=log_level)

    return replace(
        base,
        platform=platform,
        auth_mode=auth_mode,
        mcp_endpoint=mcp_endpoint,
        region=region,
        flags=flags,
        observability=observability,
    )


def load_profile(name: str | None = None) -> Profile:
    """Resolve deployment profile from name or ``DEPLOYMENT_PROFILE`` env."""
    resolved = name if name is not None else os.environ.get(PROFILE_ENV)
    if not resolved:
        raise ValueError(f"{PROFILE_ENV} is unset or empty")
    if resolved not in KNOWN_PROFILES:
        raise ValueError(f"unknown deployment profile: {resolved!r}")

    base = _PROFILE_DEFAULTS[resolved]
    return _apply_env_overrides(base)
