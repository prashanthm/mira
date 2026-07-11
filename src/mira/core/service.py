"""Warm service lifecycle — health probes and graceful SIGTERM drain (ADR-008/006).

Health probe paths: ``/health`` (liveness) and ``/health/ready`` (readiness) per
ADR-006, plus ``/health/startup`` — a Kubernetes startup probe for slow warmup
(provider init / MCP warmup). The startup path is a Mira extension of the
ADR-006 probe table; ops manifests should configure it as the K8s startupProbe.

``/explain`` (ADR-041) serves decision-trace records from an optional
:class:`~mira.core.decision_trace.TraceStore` — by ``trace_id`` (single record)
or ``correlation_id`` (all records for a request), each annotated with a
deterministic structural uncertainty summary.

``/.well-known/agent-cards`` (ADR-035) serves the deployed agent-card set for
A2A discovery from an optional ``agent_cards`` provider callable — 200 with
``{"cards": [...]}`` when configured, 503 ``discovery_unavailable`` otherwise
(fail-closed, matching the ``/explain`` unconfigured behaviour).

``GET /insights`` (ADR-006 Phase V3) serves advisory insight reports from an
optional ``insights_provider`` callable — ``(domain, refresh) -> dict | None``
that the composition root (:mod:`mira.app`) supplies (a cached wrapper over the
orchestration-layer report generator; this module stays transport-only). 200
with the report for a known ``?domain=``, 404 ``unknown_domain`` when the
provider returns None, 400 when ``domain`` is missing, 503
``insights_unavailable`` when unconfigured — the same fail-closed pattern as
``/explain``. ``?refresh=1`` asks the provider to regenerate.

``POST /turn`` (ADR-006 Phase V1) runs one streamed agent turn: the JSON body
``{"prompt": str, "thread_id"?: str}`` is delegated to an optional
``turn_handler`` factory — ``(prompt, thread_id) -> SSE WSGI handler`` — that
the composition root (:mod:`mira.app`) supplies. The service stays
transport-only: it parses/validates the request and hands the response
streaming to the handler, returning its iterable unbuffered. Unconfigured →
503 ``turns_unavailable``; non-POST → 405.

All routes are served behind the :mod:`mira.core.cors` middleware (ADR-006
Phase V1): allowed origins get their ``Origin`` echoed, ``OPTIONS`` preflight
on known paths answers 204.

When an :class:`~mira.config.slos.SloTracker` is configured (ADR-043), the
``/health`` liveness body additionally carries an ``"slos"`` summary for
operators; liveness status itself never depends on SLO health.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import threading
import urllib.parse
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from mira.config.slos import SloTracker, slo_health_payload
from mira.core.cors import wrap_cors
from mira.core.decision_trace import TraceRecord, TraceStore, uncertainty_for

StartResponse = Callable[[str, list[tuple[str, str]]], Any]
WSGIApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]
# Opaque factory the composition root supplies: (prompt, thread_id) -> an SSE
# WSGI handler for one streamed turn. Kept as a plain callable so this module
# stays framework-free (the SSE machinery lives in mira.core.streaming_sse and
# the turn semantics in mira.app).
TurnHandlerFactory = Callable[[str, str], WSGIApp]
# Insight-report provider the composition root supplies: (domain, refresh) ->
# the report dict for a registered domain, or None when the domain is unknown.
# Kept as a plain callable so this module stays framework-free (report
# generation and caching live in mira.orchestration.insights / mira.app).
InsightsProvider = Callable[[str, bool], dict[str, Any] | None]
# Multi-facet analyze provider: (symbol, question, refresh) -> the synthesized
# fan-out result dict for a ticker, or None for a blank/invalid symbol. Same
# framework-free callable shape as InsightsProvider (generation/caching live in
# mira.orchestration.analyze).
AnalyzeProvider = Callable[[str, "str | None", bool], dict[str, Any] | None]
# 0DTE SPX playbook provider: (date, refresh) -> the narrated playbook dict, or
# None. Same framework-free callable shape (generation in
# mira.orchestration.playbook).
PlaybookProvider = Callable[["str | None", bool], dict[str, Any] | None]

LIVE_PATH = "/health"
READY_PATH = "/health/ready"
STARTUP_PATH = "/health/startup"
EXPLAIN_PATH = "/explain"
AGENT_CARDS_PATH = "/.well-known/agent-cards"
TURN_PATH = "/turn"
INSIGHTS_PATH = "/insights"
ANALYZE_PATH = "/analyze"
PLAYBOOK_PATH = "/playbook"

DEFAULT_TURN_THREAD_ID = "web"

# Routes the CORS middleware answers OPTIONS preflight for.
_ROUTE_PATHS = frozenset(
    {
        LIVE_PATH,
        READY_PATH,
        STARTUP_PATH,
        EXPLAIN_PATH,
        AGENT_CARDS_PATH,
        TURN_PATH,
        INSIGHTS_PATH,
        ANALYZE_PATH,
        PLAYBOOK_PATH,
    }
)


class ServiceDrainingError(RuntimeError):
    """Raised when new in-flight work is started after drain has begun."""


class WarmService:
    """Long-running warm service with liveness/readiness probes and graceful drain."""

    def __init__(
        self,
        *,
        deps_ready: Callable[[], bool] | None = None,
        drain_timeout: float = 30.0,
        trace_store: TraceStore | None = None,
        slo_tracker: SloTracker | None = None,
        agent_cards: Callable[[], list[dict[str, Any]]] | None = None,
        turn_handler: TurnHandlerFactory | None = None,
        insights_provider: InsightsProvider | None = None,
        analyze_provider: AnalyzeProvider | None = None,
        playbook_provider: PlaybookProvider | None = None,
    ) -> None:
        self._deps_ready = deps_ready or (lambda: False)
        self._drain_timeout = drain_timeout
        self._trace_store = trace_store
        self._slo_tracker = slo_tracker
        self._agent_cards = agent_cards
        self._turn_handler = turn_handler
        self._insights_provider = insights_provider
        self._analyze_provider = analyze_provider
        self._playbook_provider = playbook_provider
        self._draining = False
        self._startup_complete = False
        # Per-scope tokens (object identity), not thread id: nested track_in_flight
        # on one thread must count as two distinct units so the inner scope exiting
        # doesn't prematurely empty _in_flight (H1).
        self._in_flight: set[object] = set()
        self._in_flight_lock = threading.Lock()
        self._drain_complete = threading.Event()

    def mark_startup_complete(self) -> None:
        """Signal that slow startup (provider init, MCP warmup) has finished."""
        self._startup_complete = True

    @property
    def draining(self) -> bool:
        return self._draining

    @contextmanager
    def track_in_flight(self) -> Iterator[None]:
        """Track a unit of in-flight work for SIGTERM drain.

        Raises :class:`ServiceDrainingError` if entered after drain has begun, so
        new work cannot extend the drain window indefinitely (M2).
        """
        token = object()
        with self._in_flight_lock:
            if self._draining:
                raise ServiceDrainingError("service is draining; not accepting new work")
            self._in_flight.add(token)
        try:
            yield
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(token)
                if self._draining and not self._in_flight:
                    self._drain_complete.set()

    def register_sigterm_handler(self, *, on_drained: Callable[[], None] | None = None) -> None:
        """Register a SIGTERM handler that drains in-flight work on a background
        thread, then invokes ``on_drained`` (defaults to ``os._exit(0)``).

        The handler itself only sets a flag and spawns the drain thread — it does
        not block in signal context (unsafe in CPython), so it cannot deadlock on
        locks held by the main thread (H2).
        """
        exit_fn = on_drained or (lambda: os._exit(0))

        def _handler(*_args: Any) -> None:
            t = threading.Thread(
                target=lambda: (self.begin_shutdown(), exit_fn()),
                name="mira-sigterm-drain",
                daemon=True,
            )
            t.start()

        signal.signal(signal.SIGTERM, _handler)

    def begin_shutdown(self) -> None:
        """Stop accepting new work, drain in-flight requests, then return when the
        in-flight set empties or the drain timeout elapses."""
        self._draining = True
        with self._in_flight_lock:
            if not self._in_flight:
                self._drain_complete.set()
        self._drain_complete.wait(timeout=self._drain_timeout)

    def is_live(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return (
            not self._draining
            and self._startup_complete
            and self._deps_ready()
        )

    def is_startup_complete(self) -> bool:
        return self._startup_complete and self._deps_ready()

    @property
    def wsgi_app(self) -> WSGIApp:
        # CORS applies to every route, including the /turn SSE response
        # (ADR-006 Phase V1); the wrapper answers OPTIONS preflight itself.
        return wrap_cors(self._handle_request, preflight_paths=_ROUTE_PATHS)

    def _handle_request(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "")
        if path == LIVE_PATH:
            payload: dict[str, Any] = {"status": "ok"}
            # SLO burn is surfaced for operators but never flips liveness:
            # a burning error budget must page (ADR-044), not restart pods.
            if self._slo_tracker is not None:
                payload["slos"] = slo_health_payload(self._slo_tracker)
            return self._json_response(start_response, 200, payload)
        if path == READY_PATH:
            if self.is_ready():
                return self._json_response(start_response, 200, {"status": "ready"})
            return self._json_response(start_response, 503, {"status": "not_ready"})
        if path == STARTUP_PATH:
            if self.is_startup_complete():
                return self._json_response(start_response, 200, {"status": "started"})
            return self._json_response(start_response, 503, {"status": "starting"})
        if path == EXPLAIN_PATH:
            return self._handle_explain(environ, start_response)
        if path == AGENT_CARDS_PATH:
            return self._handle_agent_cards(start_response)
        if path == TURN_PATH:
            return self._handle_turn(environ, start_response)
        if path == INSIGHTS_PATH:
            return self._handle_insights(environ, start_response)
        if path == ANALYZE_PATH:
            return self._handle_analyze(environ, start_response)
        if path == PLAYBOOK_PATH:
            return self._handle_playbook(environ, start_response)
        return self._json_response(start_response, 404, {"error": "not_found"})

    def _handle_turn(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        """Run one streamed turn (ADR-006 Phase V1) via the configured factory.

        Transport-only: parse/validate ``{"prompt", "thread_id"?}``, then
        delegate to the SSE handler ``turn_handler(prompt, thread_id)`` builds —
        its iterable is returned directly so frames stream unbuffered.
        """
        if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
            return self._json_response(start_response, 405, {"error": "method_not_allowed"})
        if self._turn_handler is None:
            return self._json_response(start_response, 503, {"error": "turns_unavailable"})

        try:
            body = _read_json_body(environ)
        except ValueError as exc:
            return self._json_response(
                start_response, 400, {"error": "invalid_request", "detail": str(exc)}
            )
        if not isinstance(body, dict):
            return self._json_response(
                start_response, 400, {"error": "invalid_request", "detail": "body must be a JSON object"}
            )
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return self._json_response(
                start_response,
                400,
                {"error": "invalid_request", "detail": "'prompt' must be a non-empty string"},
            )
        thread_id = body.get("thread_id", DEFAULT_TURN_THREAD_ID)
        if not isinstance(thread_id, str) or not thread_id:
            return self._json_response(
                start_response,
                400,
                {"error": "invalid_request", "detail": "'thread_id' must be a non-empty string"},
            )

        handler = self._turn_handler(prompt, thread_id)
        return handler(environ, start_response)

    def _handle_agent_cards(self, start_response: StartResponse) -> list[bytes]:
        """Serve the A2A discovery card set (ADR-035) from the cards provider."""
        if self._agent_cards is None:
            return self._json_response(
                start_response, 503, {"error": "discovery_unavailable"}
            )
        return self._json_response(start_response, 200, {"cards": self._agent_cards()})

    def _handle_insights(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> list[bytes]:
        """Serve advisory insight reports (ADR-006 Phase V3) from the provider.

        Transport-only, following the ``/explain`` pattern: unconfigured → 503;
        missing ``domain`` → 400; provider returns None (unknown domain) → 404;
        otherwise 200 with the report dict. ``?refresh=1`` (or ``true``) is
        forwarded to the provider so a scheduled job can force regeneration.
        """
        if self._insights_provider is None:
            return self._json_response(
                start_response, 503, {"error": "insights_unavailable"}
            )
        params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        domain = (params.get("domain") or [""])[0]
        if not domain:
            return self._json_response(
                start_response,
                400,
                {"error": "missing_parameter", "detail": "domain required"},
            )
        refresh = (params.get("refresh") or [""])[0].lower() in {"1", "true"}
        report = self._insights_provider(domain, refresh)
        if report is None:
            return self._json_response(start_response, 404, {"error": "unknown_domain"})
        return self._json_response(start_response, 200, report)

    def _handle_analyze(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> list[bytes]:
        """Serve a multi-facet analysis for one ticker from the analyze provider.

        GET ``?symbol=SYM[&question=...][&refresh=1]`` or POST
        ``{"symbol","question"?,"refresh"?}``. Transport-only, following the
        ``/insights`` pattern: unconfigured → 503; missing ``symbol`` → 400;
        provider returns None (blank/invalid symbol) → 404; otherwise 200 with
        the synthesized fan-out result (``{query, results, synthesis, ...}``).
        """
        if self._analyze_provider is None:
            return self._json_response(
                start_response, 503, {"error": "analyze_unavailable"}
            )
        method = environ.get("REQUEST_METHOD", "GET").upper()
        symbol = ""
        question: str | None = None
        refresh = False
        if method == "POST":
            try:
                body = _read_json_body(environ)
            except ValueError as exc:
                return self._json_response(
                    start_response, 400, {"error": "invalid_request", "detail": str(exc)}
                )
            if not isinstance(body, dict):
                return self._json_response(
                    start_response, 400,
                    {"error": "invalid_request", "detail": "body must be a JSON object"},
                )
            symbol = str(body.get("symbol", "") or "")
            q = body.get("question")
            question = str(q) if isinstance(q, str) and q.strip() else None
            refresh = bool(body.get("refresh"))
        else:
            params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
            symbol = (params.get("symbol") or [""])[0]
            q = (params.get("question") or [""])[0]
            question = q if q.strip() else None
            refresh = (params.get("refresh") or [""])[0].lower() in {"1", "true"}

        if not symbol.strip():
            return self._json_response(
                start_response, 400, {"error": "missing_parameter", "detail": "symbol required"},
            )
        result = self._analyze_provider(symbol, question, refresh)
        if result is None:
            return self._json_response(start_response, 404, {"error": "invalid_symbol"})
        return self._json_response(start_response, 200, result)

    def _handle_playbook(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> list[bytes]:
        """Serve the narrated 0DTE SPX playbook from the playbook provider.

        GET ``?date=YYYY-MM-DD&refresh=1`` (both optional; latest when no date).
        Unconfigured → 503. Returns ``{available, session, scaffold, narrative,
        draft}``; ``{available:false}`` (200) when no playbook has been generated.
        Context, not a signal (ADR-008)."""
        if self._playbook_provider is None:
            return self._json_response(
                start_response, 503, {"error": "playbook_unavailable"})
        params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        date = (params.get("date") or [""])[0] or None
        refresh = (params.get("refresh") or [""])[0].lower() in {"1", "true"}
        result = self._playbook_provider(date, refresh)
        if result is None:
            return self._json_response(start_response, 200, {"available": False})
        return self._json_response(start_response, 200, result)

    def _handle_explain(
        self,
        environ: dict[str, Any],
        start_response: StartResponse,
    ) -> list[bytes]:
        """Serve decision-trace explanations (ADR-041) from the trace store."""
        if self._trace_store is None:
            return self._json_response(
                start_response, 503, {"error": "explanations_unavailable"}
            )
        params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        trace_id = (params.get("trace_id") or [""])[0]
        correlation_id = (params.get("correlation_id") or [""])[0]
        if trace_id:
            record = self._trace_store.get(trace_id)
            if record is None:
                return self._json_response(start_response, 404, {"error": "trace_not_found"})
            return self._json_response(start_response, 200, _explain_payload(record))
        if correlation_id:
            records = self._trace_store.for_correlation(correlation_id)
            return self._json_response(
                start_response,
                200,
                {"records": [_explain_payload(record) for record in records]},
            )
        return self._json_response(
            start_response,
            400,
            {"error": "missing_parameter", "detail": "trace_id or correlation_id required"},
        )

    @staticmethod
    def _json_response(
        start_response: StartResponse,
        status_code: int,
        payload: dict[str, Any],
    ) -> list[bytes]:
        body = json.dumps(payload).encode("utf-8")
        reason = http.client.responses.get(status_code, "Unknown")
        status = f"{status_code} {reason}"
        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ]
        start_response(status, headers)
        return [body]


def _read_json_body(environ: dict[str, Any]) -> Any:
    """Read and parse the JSON request body from ``CONTENT_LENGTH`` + ``wsgi.input``.

    Raises :class:`ValueError` (which :class:`json.JSONDecodeError` subclasses)
    on a missing, unreadable, or malformed body.
    """
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length") from exc
    if length <= 0:
        raise ValueError("request body required")
    raw = environ["wsgi.input"].read(length)
    if not raw:
        raise ValueError("request body required")
    return json.loads(raw.decode("utf-8"))


def _explain_payload(record: TraceRecord) -> dict[str, Any]:
    """Trace record as an /explain response body, with the uncertainty block."""
    payload = record.to_dict()
    payload["uncertainty"] = uncertainty_for(record)
    return payload


def create_app(
    *,
    deps_ready: Callable[[], bool] | None = None,
    trace_store: TraceStore | None = None,
    slo_tracker: SloTracker | None = None,
    agent_cards: Callable[[], list[dict[str, Any]]] | None = None,
    turn_handler: TurnHandlerFactory | None = None,
    insights_provider: InsightsProvider | None = None,
) -> WarmService:
    """Build a warm service with health, /explain, discovery, /turn, /insights routes."""
    return WarmService(
        deps_ready=deps_ready,
        trace_store=trace_store,
        slo_tracker=slo_tracker,
        agent_cards=agent_cards,
        turn_handler=turn_handler,
        insights_provider=insights_provider,
    )
