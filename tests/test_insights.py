"""Tests for the insight report (orchestration/insights) and the /insights route.

All offline: the advisor specialist runs over the fake ``vantage.*`` tools, and
endpoint behaviour is exercised at the WSGI level following the /explain tests.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from mira.core.service import INSIGHTS_PATH, WarmService, create_app
from mira.orchestration.agent_cards import AgentCardRegistry
from mira.orchestration.insights import (
    ADVISORY_DISCLAIMER,
    DEFAULT_INSIGHT_QUERIES,
    InsightReport,
    cached_insights_provider,
    generate_insight_report,
)
from mira.orchestration.specialists.advisor import (
    advisor_registry_entry,
    build_advisor_specialist,
)

from tests.fake_vantage import fake_vantage_registered_tools


def _report(**kwargs: Any) -> InsightReport:
    specialist = build_advisor_specialist(fake_vantage_registered_tools(**kwargs))
    return generate_insight_report(specialist, thread_id="test")


def _advisor_registry() -> AgentCardRegistry:
    registry = AgentCardRegistry()
    card, factory = advisor_registry_entry(fake_vantage_registered_tools())
    registry.register(card, factory)
    return registry


def _call_wsgi(app, path: str, query_string: str = "") -> tuple[int, dict[str, Any]]:
    status_holder: list[str] = []

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        status_holder.append(status)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
        "wsgi.input": BytesIO(b""),
        "wsgi.errors": None,
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
    }
    body = b"".join(app(environ, start_response))
    status_code = int(status_holder[0].split()[0])
    return status_code, json.loads(body.decode("utf-8"))


# ── report shape & determinism ───────────────────────────────────────────────


def test_report_shape_covers_the_default_battery() -> None:
    report = _report()

    assert report.generated_for == "advisor"
    assert [insight.topic for insight in report.observations] == [
        "wash_status",
        "tlh_candidates",
        "allocation",
    ]
    assert len(DEFAULT_INSIGHT_QUERIES) == 3
    for insight in report.observations:
        assert insight.detail
        assert insight.evidence
        assert insight.provenance["source_type"] == "vantage"
        assert insight.provenance["source_id"].startswith("/data/vantage#")


def test_report_is_deterministic_across_fresh_runs() -> None:
    assert _report().to_dict() == _report().to_dict()


def test_report_to_dict_is_json_safe() -> None:
    payload = _report().to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) == {
        "summary",
        "observations",
        "suggestions",
        "confidence",
        "caveats",
        "generated_for",
    }


def test_suggestions_are_advisory_observations_not_instructions() -> None:
    report = _report()
    assert report.suggestions  # blocked wash + clear TLH lots in the fake data
    for suggestion in report.suggestions:
        assert suggestion.startswith("Observation:")


# ── confidence heuristic & disclaimer ────────────────────────────────────────


def test_all_grounded_error_free_battery_is_medium_never_high() -> None:
    report = _report()
    assert report.confidence == "medium"


def test_tool_error_lowers_confidence_and_lands_in_caveats() -> None:
    report = _report(failing={"vantage.wash_status"})

    assert report.confidence == "low"
    assert "tool_error" in report.caveats
    assert "vantage.wash_status" in report.caveats
    # The failed query contributes no observation; the rest still ground.
    assert [insight.topic for insight in report.observations] == [
        "tlh_candidates",
        "allocation",
    ]


def test_ungrounded_battery_is_low_confidence() -> None:
    # A battery the advisor cannot map to any tool → noop answers, no provenance.
    specialist = build_advisor_specialist(fake_vantage_registered_tools())
    report = generate_insight_report(
        specialist, queries=("tell me a story",), thread_id="test-ungrounded"
    )
    assert report.confidence == "low"


def test_disclaimer_always_present_in_caveats() -> None:
    assert ADVISORY_DISCLAIMER in _report().caveats
    assert ADVISORY_DISCLAIMER in _report(failing={"vantage.allocation"}).caveats


# ── cached provider ──────────────────────────────────────────────────────────


def test_cached_provider_serves_known_domains_and_none_for_unknown() -> None:
    provider = cached_insights_provider(_advisor_registry())

    report = provider("advisor", False)
    assert report is not None and report["generated_for"] == "advisor"
    assert provider("advisor", False) is report  # cache hit: same object
    assert provider("nope", False) is None


def test_cached_provider_refresh_regenerates() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    registry = AgentCardRegistry()
    card, factory = advisor_registry_entry(fake_vantage_registered_tools(calls=calls))
    registry.register(card, factory)
    provider = cached_insights_provider(registry)

    provider("advisor", False)
    first_calls = len(calls)
    provider("advisor", False)
    assert len(calls) == first_calls  # cached: no new tool dispatches
    provider("advisor", True)
    assert len(calls) > first_calls  # refresh re-ran the battery


# ── /insights endpoint (WSGI level) ──────────────────────────────────────────


def _service() -> WarmService:
    return create_app(
        deps_ready=lambda: True,
        insights_provider=cached_insights_provider(_advisor_registry()),
    )


def test_insights_endpoint_returns_report_for_known_domain() -> None:
    status, payload = _call_wsgi(_service().wsgi_app, INSIGHTS_PATH, "domain=advisor")

    assert status == 200
    assert payload["generated_for"] == "advisor"
    assert payload["confidence"] == "medium"
    assert ADVISORY_DISCLAIMER in payload["caveats"]
    assert payload["observations"][0]["provenance"]["source_type"] == "vantage"


def test_insights_endpoint_unknown_domain_returns_404() -> None:
    status, payload = _call_wsgi(_service().wsgi_app, INSIGHTS_PATH, "domain=nope")
    assert status == 404
    assert payload == {"error": "unknown_domain"}


def test_insights_endpoint_missing_domain_returns_400() -> None:
    status, payload = _call_wsgi(_service().wsgi_app, INSIGHTS_PATH)
    assert status == 400
    assert payload["error"] == "missing_parameter"


def test_insights_endpoint_unconfigured_returns_503() -> None:
    service = create_app(deps_ready=lambda: True)  # no insights provider
    status, payload = _call_wsgi(service.wsgi_app, INSIGHTS_PATH, "domain=advisor")
    assert status == 503
    assert payload == {"error": "insights_unavailable"}


def test_insights_endpoint_refresh_regenerates() -> None:
    generations: list[bool] = []

    def provider(domain: str, refresh: bool) -> dict[str, Any] | None:
        if domain != "advisor":
            return None
        generations.append(refresh)
        return {"generated_for": domain, "refreshed": refresh}

    service = create_app(deps_ready=lambda: True, insights_provider=provider)

    status, payload = _call_wsgi(service.wsgi_app, INSIGHTS_PATH, "domain=advisor")
    assert status == 200 and payload["refreshed"] is False
    status, payload = _call_wsgi(
        service.wsgi_app, INSIGHTS_PATH, "domain=advisor&refresh=1"
    )
    assert status == 200 and payload["refreshed"] is True
    assert generations == [False, True]


def test_health_routes_unaffected_by_insights_provider() -> None:
    status, payload = _call_wsgi(_service().wsgi_app, "/health")
    assert status == 200
    assert payload == {"status": "ok"}
