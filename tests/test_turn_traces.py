"""Supervisor-routed turns land in the decision-trace store (ADR-040/041)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from mira.app import build_app
from mira.orchestration.specialists.demo import build_demo_registry
from mira.orchestration.specialists.research import REPRESENTATIVE_RESEARCH_QUERY
from mira.providers.local import build_local_bundle

FIXTURES = Path(__file__).parent / "fixtures"


def _app():
    registry = build_demo_registry(
        str(FIXTURES / "handbook.md"), str(FIXTURES / "ledger.csv")
    )
    return build_app("kubernetes", bundle=build_local_bundle(), registry=registry)


def _run_turn(app, prompt: str) -> list[tuple[str, dict]]:
    """Drive POST /turn at the WSGI level; return parsed (kind, data) frames."""
    body = json.dumps({"prompt": prompt, "thread_id": "trace-test"}).encode()
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/turn",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status

    chunks = b"".join(
        c if isinstance(c, bytes) else c.encode()
        for c in app.wsgi_app(environ, start_response)
    )
    assert captured["status"].startswith("200")
    frames = []
    for frame in chunks.decode().split("\n\n"):
        if not frame.strip():
            continue
        kind = data = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                kind = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        frames.append((kind, data))
    return frames


def test_routed_turn_is_recorded_under_its_correlation_id():
    app = _app()
    frames = _run_turn(app, REPRESENTATIVE_RESEARCH_QUERY)

    done = [data for kind, data in frames if kind == "done"]
    assert done and done[0]["correlation_id"]
    correlation_id = done[0]["correlation_id"]

    records = app.trace_store.for_correlation(correlation_id)
    assert len(records) == 1
    record = records[0]
    assert record.correlation_id == correlation_id
    assert record.plan_steps  # the specialist's visible plan carried over
    assert any(  # grounded claim→source edge from the docs answer
        claim.source_type == "docs" for claim in record.claims
    )


def test_explain_serves_the_recorded_turn():
    app = _app()
    frames = _run_turn(app, REPRESENTATIVE_RESEARCH_QUERY)
    correlation_id = [d for k, d in frames if k == "done"][0]["correlation_id"]

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/explain",
        "QUERY_STRING": f"correlation_id={correlation_id}",
    }
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status

    body = b"".join(app.wsgi_app(environ, start_response))
    assert captured["status"].startswith("200")
    payload = json.loads(body)
    assert payload["records"], "explain must return the recorded turn"
    assert "uncertainty" in payload["records"][0]


def test_fallback_turns_are_not_traced():
    app = _app()
    before = len(app.trace_store.all())
    _run_turn(app, "qwerty zxcvb completely unmatched")
    assert len(app.trace_store.all()) == before  # general path records nothing
