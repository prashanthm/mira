"""Per-agent identity and task-scoped tokens (ADR-034).

ADR-034 adopts OAuth 2.0 Token Exchange (RFC 8693): at dispatch time the
supervisor exchanges its broader credential for a **short-lived, task-scoped
token** narrowed to the tool surface and entitlements the current task needs.
This module is the framework-free, offline-testable shape of that exchange:

* :class:`AgentIdentity` — the stable per-agent subject (the specialist's
  ``domain_id`` plus display metadata), the RFC 8693 *subject* of an exchange.
* :class:`TaskToken` — the minted, scoped credential: agent name, allowed tool
  prefixes, entitlements, issue/expiry instants, and an HMAC-SHA256 signature
  over the canonical field string (stdlib ``hmac`` — a real deployment swaps in
  the IdP's JWT signing behind the same shape).
* :class:`TokenExchanger` — mints and validates tokens. The clock is
  **injected and required** (no wall-clock default) so expiry behaviour is
  deterministic under test, matching the repo-wide injectable-clock rule.

Fail-closed throughout: an invalid or expired token allows no tool at all
(:meth:`TokenExchanger.scope_allows` returns ``False`` before any prefix
check), and prefix scoping only ever *narrows* — a token with no prefixes
allows nothing.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Iterable
from dataclasses import dataclass

ClockFn = Callable[[], float]

_CANONICAL_SEPARATOR = "|"
_LIST_SEPARATOR = ","


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Stable per-agent identity: the specialist's domain id + display metadata."""

    agent_name: str
    display_name: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class TaskToken:
    """A short-lived, task-scoped credential minted per dispatch (ADR-034).

    ``tool_prefixes`` narrows which MCP tool names the holder may call;
    ``entitlements`` names the entitlement grants the token carries to the
    inherited MCP enforcement boundary. ``signature`` is the hex HMAC-SHA256
    over the canonical field string.
    """

    agent_name: str
    tool_prefixes: frozenset[str]
    entitlements: frozenset[str]
    issued_at: float
    expires_at: float
    signature: str


def _canonical_string(
    agent_name: str,
    tool_prefixes: Iterable[str],
    entitlements: Iterable[str],
    issued_at: float,
    expires_at: float,
) -> str:
    """Deterministic field string the signature covers (sorted collections)."""
    return _CANONICAL_SEPARATOR.join(
        (
            agent_name,
            _LIST_SEPARATOR.join(sorted(tool_prefixes)),
            _LIST_SEPARATOR.join(sorted(entitlements)),
            repr(issued_at),
            repr(expires_at),
        )
    )


class TokenExchanger:
    """RFC 8693-shaped exchange: subject identity → scoped, short-lived token.

    ``secret`` keys the HMAC; ``clock`` is required (injectable, no wall-clock
    default); ``ttl_seconds`` bounds each minted token's lifetime. Key rotation
    is deferred (ADR-034 Phase-F note): one exchanger holds one key, and a
    rotation story layers a key-id into the canonical string without changing
    this contract.
    """

    def __init__(self, secret: bytes, *, clock: ClockFn, ttl_seconds: float = 300.0) -> None:
        if not secret:
            raise ValueError("TokenExchanger requires a non-empty secret")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._secret = secret
        self._clock = clock
        self._ttl_seconds = ttl_seconds

    def _sign(self, canonical: str) -> str:
        return hmac.new(self._secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def mint(
        self,
        identity: AgentIdentity,
        *,
        tool_prefixes: Iterable[str],
        entitlements: Iterable[str],
    ) -> TaskToken:
        """Mint a task-scoped token for ``identity`` narrowed to the given scope."""
        issued_at = self._clock()
        expires_at = issued_at + self._ttl_seconds
        prefixes = frozenset(tool_prefixes)
        grants = frozenset(entitlements)
        signature = self._sign(
            _canonical_string(identity.agent_name, prefixes, grants, issued_at, expires_at)
        )
        return TaskToken(
            agent_name=identity.agent_name,
            tool_prefixes=prefixes,
            entitlements=grants,
            issued_at=issued_at,
            expires_at=expires_at,
            signature=signature,
        )

    def validate(self, token: TaskToken) -> bool:
        """True iff the signature verifies and the token has not expired."""
        expected = self._sign(
            _canonical_string(
                token.agent_name,
                token.tool_prefixes,
                token.entitlements,
                token.issued_at,
                token.expires_at,
            )
        )
        if not hmac.compare_digest(expected, token.signature):
            return False
        return self._clock() < token.expires_at

    def scope_allows(self, token: TaskToken, tool_name: str) -> bool:
        """Fail-closed prefix scoping: invalid/expired tokens allow nothing."""
        if not self.validate(token):
            return False
        return any(tool_name.startswith(prefix) for prefix in token.tool_prefixes)


__all__ = ["AgentIdentity", "ClockFn", "TaskToken", "TokenExchanger"]
