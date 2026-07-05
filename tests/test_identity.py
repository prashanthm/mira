"""Tests for per-agent identity and task-scoped tokens (ADR-034)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mira.core.identity import AgentIdentity, TokenExchanger


class FakeClock:
    """Deterministic injectable clock."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


FINANCE = AgentIdentity(agent_name="finance", display_name="Finance Specialist")


def _exchanger(clock: FakeClock, ttl: float = 300.0) -> TokenExchanger:
    return TokenExchanger(b"test-secret", clock=clock, ttl_seconds=ttl)


def test_mint_produces_scoped_signed_token():
    clock = FakeClock(1000.0)
    token = _exchanger(clock).mint(
        FINANCE,
        tool_prefixes=["ledger."],
        entitlements=["connector:ledger:query"],
    )
    assert token.agent_name == "finance"
    assert token.tool_prefixes == frozenset({"ledger."})
    assert token.entitlements == frozenset({"connector:ledger:query"})
    assert token.issued_at == 1000.0
    assert token.expires_at == 1300.0
    assert token.signature and int(token.signature, 16)  # hex HMAC digest


def test_validate_accepts_fresh_token_and_rejects_expired():
    clock = FakeClock()
    exchanger = _exchanger(clock, ttl=60.0)
    token = exchanger.mint(FINANCE, tool_prefixes=["ledger."], entitlements=[])

    assert exchanger.validate(token)
    clock.advance(59.9)
    assert exchanger.validate(token)
    clock.advance(0.2)  # past expires_at
    assert not exchanger.validate(token)


def test_validate_rejects_tampered_fields():
    clock = FakeClock()
    exchanger = _exchanger(clock)
    token = exchanger.mint(FINANCE, tool_prefixes=["ledger."], entitlements=[])

    widened = replace(token, tool_prefixes=frozenset({"ledger.", "docs."}))
    extended = replace(token, expires_at=token.expires_at + 3600.0)
    impersonated = replace(token, agent_name="research")

    assert not exchanger.validate(widened)
    assert not exchanger.validate(extended)
    assert not exchanger.validate(impersonated)


def test_validate_rejects_foreign_secret():
    clock = FakeClock()
    token = _exchanger(clock).mint(FINANCE, tool_prefixes=["ledger."], entitlements=[])
    other = TokenExchanger(b"other-secret", clock=clock)
    assert not other.validate(token)


def test_scope_allows_prefix_match_only():
    clock = FakeClock()
    exchanger = _exchanger(clock)
    token = exchanger.mint(FINANCE, tool_prefixes=["ledger."], entitlements=[])

    assert exchanger.scope_allows(token, "ledger.query")
    assert exchanger.scope_allows(token, "ledger.categories")
    assert not exchanger.scope_allows(token, "docs.search")


def test_scope_fails_closed_on_expired_or_invalid_token():
    clock = FakeClock()
    exchanger = _exchanger(clock, ttl=10.0)
    token = exchanger.mint(FINANCE, tool_prefixes=["ledger."], entitlements=[])

    clock.advance(11.0)
    assert not exchanger.scope_allows(token, "ledger.query")

    fresh = exchanger.mint(FINANCE, tool_prefixes=["ledger."], entitlements=[])
    forged = replace(fresh, signature="00" * 32)
    assert not exchanger.scope_allows(forged, "ledger.query")


def test_empty_prefixes_allow_nothing():
    clock = FakeClock()
    exchanger = _exchanger(clock)
    token = exchanger.mint(FINANCE, tool_prefixes=[], entitlements=[])
    assert exchanger.validate(token)
    assert not exchanger.scope_allows(token, "ledger.query")


def test_constructor_guards():
    clock = FakeClock()
    with pytest.raises(ValueError, match="non-empty secret"):
        TokenExchanger(b"", clock=clock)
    with pytest.raises(ValueError, match="ttl_seconds"):
        TokenExchanger(b"k", clock=clock, ttl_seconds=0.0)
