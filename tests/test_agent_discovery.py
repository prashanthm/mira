"""Tests for the A2A agent-card discovery route (ADR-035) on the warm service."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.core.service import AGENT_CARDS_PATH, create_app
from mira.orchestration.agent_cards import AgentCard


def _call_wsgi(app, path: str) -> tuple[int, dict[str, Any]]:
    status_holder: list[str] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder.append(status)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "wsgi.input": BytesIO(b""),
    }
    body = b"".join(app.wsgi_app(environ, start_response))
    return int(status_holder[0].split()[0]), json.loads(body.decode("utf-8"))


def _cards() -> list[dict[str, Any]]:
    return [
        AgentCard(
            name="finance",
            description="Spend questions over the ledger",
            tool_prefixes=frozenset({"ledger."}),
            keywords=frozenset({"spend", "ledger"}),
        ).to_dict()
    ]


def test_well_known_path_matches_adr_035():
    assert AGENT_CARDS_PATH == "/.well-known/agent-cards"


def test_discovery_returns_configured_cards():
    service = create_app(deps_ready=lambda: True, agent_cards=_cards)
    status, payload = _call_wsgi(service, AGENT_CARDS_PATH)

    assert status == 200
    assert payload == {"cards": _cards()}
    card = payload["cards"][0]
    assert card["capabilities"]["tool_prefixes"] == ["ledger."]


def test_discovery_unconfigured_is_503():
    service = create_app(deps_ready=lambda: True)
    status, payload = _call_wsgi(service, AGENT_CARDS_PATH)
    assert status == 503
    assert payload == {"error": "discovery_unavailable"}


def test_provider_is_called_per_request():
    calls: list[int] = []

    def provider() -> list[dict[str, Any]]:
        calls.append(1)
        return []

    service = create_app(deps_ready=lambda: True, agent_cards=provider)
    _call_wsgi(service, AGENT_CARDS_PATH)
    _call_wsgi(service, AGENT_CARDS_PATH)
    assert len(calls) == 2


def test_existing_routes_unaffected():
    service = create_app(deps_ready=lambda: True, agent_cards=_cards)
    service.mark_startup_complete()
    assert _call_wsgi(service, "/health")[0] == 200
    assert _call_wsgi(service, "/health/ready")[0] == 200
    assert _call_wsgi(service, "/nope")[0] == 404
