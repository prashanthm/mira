"""End-to-end app composition tests (e03-f07).

Boots the composed app with a fake, network-free provider bundle, asserts the
warm service reports ready, and runs one non-streaming end-to-end turn through
the runtime-behind-gateway composition.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.app import App, build_app
from mira.core.service import READY_PATH
from mira.providers.bundle import ProviderBundle


class _FakeLLM:
    """Deterministic in-memory LLM — no network, no vendor SDK."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        self.calls.append(prompt)
        return f"echo:{prompt}"

    def embed(self, text: str) -> list[float]:
        return [float(len(text))]


class _FakeStateStore:
    def __init__(self) -> None:
        self._state: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._state.get(key)

    def set(self, key: str, value: str) -> None:
        self._state[key] = value


def _fake_bundle() -> tuple[ProviderBundle, _FakeLLM]:
    llm = _FakeLLM()
    bundle = ProviderBundle(
        llm=llm,
        secrets=object(),  # type: ignore[arg-type]
        object_store=object(),  # type: ignore[arg-type]
        state_store=_FakeStateStore(),
        observability=object(),  # type: ignore[arg-type]
    )
    return bundle, llm


def _call_wsgi(app: Any, path: str) -> tuple[int, dict[str, Any]]:
    status_holder: list[str] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder.append(status)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "wsgi.input": BytesIO(b""),
    }
    body = b"".join(app(environ, start_response))
    status_code = int(status_holder[0].split()[0])
    payload = json.loads(body.decode("utf-8"))
    return status_code, payload


def _build() -> tuple[App, _FakeLLM]:
    bundle, llm = _fake_bundle()
    # Explicit profile keeps the test independent of ambient DEPLOYMENT_PROFILE.
    return build_app("kubernetes", bundle=bundle), llm


def test_build_app_composes_runtime_behind_gateway() -> None:
    app, _ = _build()
    # The runtime calls through the gateway, which delegates to the bundle's LLM.
    assert app.gateway.complete("ping") == "echo:ping"
    assert app.profile.name == "kubernetes"


def test_local_profile_degrades_when_mcp_unavailable() -> None:
    # The `local` profile defaults mcp_endpoint to localhost MCP server. Whether the [mcp]
    # extra is missing or the server is simply not running at build time, discovery must
    # degrade to zero tools and still compose a runnable app (network-free boot survives).
    bundle, _ = _fake_bundle()
    app = build_app("local", bundle=bundle)
    assert app.profile.name == "local"
    assert app.profile.mcp_endpoint == "http://localhost:8000/mcp"
    # Turn still runs through the gateway with no MCP tools bound.
    result = app.run_turn("ping")
    assert result["response"] == "echo:ping"


def test_health_ready_returns_200_after_boot() -> None:
    app, _ = _build()
    status, payload = _call_wsgi(app.wsgi_app, READY_PATH)
    assert status == 200
    assert payload == {"status": "ready"}


def test_one_end_to_end_turn_reaches_a_result() -> None:
    app, llm = _build()
    result = app.run_turn("hello agent", thread_id="t1")

    # The LLM ran exactly once through the gateway with our prompt.
    assert llm.calls == ["hello agent"]
    # One non-streaming turn produced a response and paused at the human gate.
    assert result["response"] == "echo:hello agent"
    assert app.runtime.is_paused(result)


# --- ADR-052: tier-aware gateway wiring ---------------------------------------


def test_gateway_from_env_is_plain_gateway_without_model_routes(monkeypatch):
    from mira.app import _gateway_from_env
    from mira.providers.local import build_local_bundle

    monkeypatch.delenv("MODEL_ROUTES", raising=False)
    gateway = _gateway_from_env(build_local_bundle(), None)
    # No router/policy wired: the tier kwarg is inert and delegation is direct.
    assert gateway._router is None and gateway._tier_policy is None


def test_gateway_from_env_builds_router_and_policy_from_cards(monkeypatch):
    import json

    from mira.app import _gateway_from_env
    from mira.orchestration.agent_cards import AgentCardRegistry
    from mira.orchestration.specialists.demo import FINANCE_CARD, RESEARCH_CARD
    from mira.providers.local import build_local_bundle

    monkeypatch.setenv(
        "MODEL_ROUTES",
        json.dumps(
            [
                {"provider": "d", "model": "cheap", "tier": "light", "cost_per_1k_tokens": 0.3},
                {"provider": "d", "model": "big", "tier": "deep", "cost_per_1k_tokens": 2.0},
            ]
        ),
    )
    registry = AgentCardRegistry()
    registry.register(RESEARCH_CARD, lambda: None)
    registry.register(FINANCE_CARD, lambda: None)
    gateway = _gateway_from_env(build_local_bundle(), registry)
    assert gateway._router is not None
    assert gateway._tier_policy.agent_tiers == {"research": "light", "finance": "standard"}
    # Card hint resolves; explicit tier still wins.
    assert gateway._tier_policy.resolve("q", agent="research") == "light"
    assert gateway._tier_policy.resolve("q", agent="research", explicit="deep") == "deep"


def test_gateway_from_env_raises_on_malformed_json(monkeypatch):
    import pytest as _pytest

    from mira.app import _gateway_from_env
    from mira.providers.local import build_local_bundle

    monkeypatch.setenv("MODEL_ROUTES", "{not json")
    with _pytest.raises(Exception):
        _gateway_from_env(build_local_bundle(), None)


def test_build_app_binds_runtime_to_general_agent_identity(monkeypatch):
    from mira.app import build_app
    from mira.model.gateway import _AgentBoundLLM
    from mira.providers.local import build_local_bundle

    monkeypatch.delenv("MODEL_ROUTES", raising=False)
    app = build_app("kubernetes", bundle=build_local_bundle())
    assert isinstance(app.runtime._llm, _AgentBoundLLM)
    assert app.runtime._llm._agent == "general"
    # And a turn still works end to end through the bound view.
    assert app.run_turn("hello")["response"]
