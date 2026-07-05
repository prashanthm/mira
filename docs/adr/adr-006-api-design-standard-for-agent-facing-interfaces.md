# ADR-006: API Design Standard for Agent-Facing Interfaces

## Status

Accepted

## Context

Client surfaces ([ADR-005](./adr-005-client-surface-boundary.md)) call a **Mira Agent API** distinct from the inherited **MCP tool API** (MCP-server ADR-002). The product brief requires **streaming responses** and **visible planning** (MIRA-RUNTIME). The hardening decisions define `/invocations` compatibility, HITL webhooks (D3), and OTel root spans (D4).

This ADR standardizes HTTP/WebSocket conventions for the agent layer. MCP tool design (outcome-oriented tools, `_llm_context`) remains owned by the MCP tool server.

## Decision Drivers

1. **MIRA-RUNTIME epic** — "WebSocket/streaming", plan visibility, warm persistent runtime.
2. **Hardening constraint** — preserve backward-compatible **`/invocations`** endpoint (Bedrock AgentCore / existing integrations).
3. **Design decision D3** — HITL via **async webhook callback**, not blocking WebSocket.
4. **Design decision D4** — OTel root span at `/invocations`; correlation ID propagation (inherited MCP-server ADR-012).
5. **Inherited rate limiting** — agent treats MCP 429 as signal (MCP-server ADR-008); agent layer may add RPM limits via middleware.

## Decision

Implement the Agent API as a **FastAPI** service with the following standards.

**Core endpoints (Phase 1+):**

| Endpoint | Method / transport | Purpose |
|----------|-------------------|---------|
| `/invocations` | POST (HTTP) | Primary agent invocation; **must remain backward compatible** with existing Bedrock AgentCore contract |
| `/invocations/stream` | POST → SSE **or** WebSocket | Token streaming + **live plan events** (product-brief requirement) |
| `/health` | GET | Liveness probe (process up) |
| `/health/ready` | GET | Readiness (providers initialized, MCP reachable) |
| `/explain` | GET/POST | Decision trace / attribution (contract defined Phase 1; full XAI Phase 3 — MIRA-XAI) |
| `/escalation/callback` | POST | HITL async webhook receiver (design decision D3) |

**Design rules:**

1. **JSON request/response** — `Content-Type: application/json`; UTF-8; snake_case field names in JSON bodies.
2. **Errors** — structured body: `{ "error": { "code": "<machine>", "message": "<human>", "correlation_id": "<uuid>", "retryable": bool } }`; HTTP status follows problem semantics (401 auth, 429 rate limit, 503 upstream).
3. **Correlation** — accept `X-Correlation-ID` header; if absent, generate UUID v4; bind to structlog context and forward to MCP (inherited MCP-server ADR-012).
4. **Streaming** — SSE default for broad client compatibility; WebSocket optional for bidirectional plan UX; stream event types: `token`, `plan_step`, `tool_call`, `done`, `error`. Prefer **SSE** for one-way token streaming and plan events (chat UI default). Use **WebSocket** only when bidirectional UX is required (live tool-call interjection, plan revision mid-stream); do not implement both transports for the same client surface unless both modes are explicitly needed.
5. **Versioning** — URL prefix `/v1/` is the **canonical** addressing mode for versioned routes (example: `POST /v1/invocations/stream`). The unversioned `POST /invocations` path is preserved for Bedrock AgentCore compatibility and internally routes to the current handler. `Accept-Version: 1` is an optional client hint for SDK convenience; when header and URL disagree, **URL prefix wins**. Example: `POST /v1/invocations` with `Accept-Version: 2` → serve v1 contract (HTTP 200) or reject with `400` if v2 is unsupported — never silently cross-version.
6. **Auth** — `Authorization: Bearer <JWT>` on all endpoints **except** `/health` and `/health/ready` (no auth; aligns with MCP-server ADR-014 probe expectations). JWT validation rules are defined in [ADR-033](./adr-033-phase-1-minimum-identity-slice.md).
7. **Rate limiting** — agent middleware enforces per-user RPM (configurable; the infra-hardening spec proposes ~30 RPM default); MCP 429 responses surfaced to client with `retry_after` when present.

**Phase deferrals:**

- `/explain` full payload — Phase 3 (MIRA-XAI); Phase 1 returns `501 Not Implemented` or stub with correlation ID only.
- Webhook signature verification for HITL — specified in ADR-039 (Proposed; see [adr-list.md](./adr-list.md)); endpoint reserved in Phase 1 schema.

**Rejected alternatives:**

- **GraphQL** — Rejected: poor fit for token streaming and large binary payloads; team stack is FastAPI/REST; MCP already covers structured tool queries.
- **Rename or remove `/invocations`** — Rejected: explicit hardening non-goal; breaks AgentCore integration path.
- **WebSocket-only API** — Rejected: health probes, HITL callbacks, and load balancers need plain HTTP; D3 rejected sync WebSocket-only escalation.
- **gRPC external API** — Rejected: browser clients and portal integrations expect HTTP; adds second contract surface without consumer demand.

## Consequences

### Becomes Easier

- Client teams (chat, SDK) integrate against one documented contract.
- K8s probes and service mesh routing use standard HTTP health paths (MCP-server ADR-014 pattern).
- Streaming and plan visibility share one event envelope.

### Becomes Harder

- Maintaining `/invocations` compatibility constrains handler refactors — requires adapter layer for legacy payloads.
- Dual streaming transports (SSE + WebSocket) need parallel test coverage.
- Version header discipline required to avoid breaking SDK consumers silently.

## Verification

Contract tests required before MIRA-RUNTIME Phase 1 sign-off (implementation spec may expand fixtures):

1. **Legacy `/invocations`** — representative Bedrock AgentCore payload accepted byte-for-byte; response shape unchanged from compatibility baseline.
2. **SSE streaming** — event schema and order (`token` → `plan_step`/`tool_call` → `done`/`error`); `Content-Type: text/event-stream`.
3. **WebSocket parity** — same event types and ordering as SSE for equivalent invocation scenarios.
4. **Rate-limit propagation** — MCP `429` surfaced to client with `retry_after` when present.
5. **Health probes** — `GET /health` and `GET /health/ready` return 200/503 without `Authorization` header.

## Applies To

- **MIRA-RUNTIME** — primary implementation epic
- **MIRA-REASON** — plan stream events (Phase 2)
- **MIRA-XAI** — `/explain` (Phase 3)
- **MIRA-SAFETY** — escalation callback (Phase 3)
- [ADR-005](./adr-005-client-surface-boundary.md) — client surfaces; [ADR-009](./adr-009-middleware-pipeline-architecture.md) — middleware pipeline
- [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — JWT validation rules
- Inherited: MCP-server ADR-012 (correlation ID propagation), MCP-server ADR-014 (health endpoint design)

## Links

- ADR file: `docs/adr/adr-006-api-design-standard-for-agent-facing-interfaces.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-006
- Hardening decisions: D3 HITL, D4 tracing — production-hardening spec set

## Implemented Mechanism (Phase V1)

The decision above is unchanged. This section records the Phase V1 slice of the
HTTP/AI surface as built: one streamed-turn route, CORS for browser clients, and
the dev-server posture.

### `POST /turn` — streamed turn (SSE)

`WarmService` (`src/mira/core/service.py`) routes `POST /turn` and delegates the
response to an SSE handler factory the composition root (`mira.app.App`)
supplies — the service stays transport-only (parse + validate + delegate,
response never buffered). This is the Phase V1 realization of the
`/invocations/stream` row in the endpoint table; the `/invocations` +
`/v1/`-prefixed addressing lands with the full FastAPI surface.

Request:

```json
{ "prompt": "<non-empty string>", "thread_id": "<optional string, default \"web\">" }
```

Responses:

| Case | Status / body |
|------|---------------|
| Success | `200`, `Content-Type: text/event-stream` — frames stream unbuffered |
| Missing/invalid `prompt` (or malformed body) | `400 {"error": "invalid_request", "detail": "..."}` |
| Non-POST method on `/turn` | `405 {"error": "method_not_allowed"}` |
| No turn handler configured | `503 {"error": "turns_unavailable"}` |

Stream frames use the event types this ADR standardizes (`token`, `plan_step`,
`tool_call`, `done`, `error`); each frame is `event: <kind>` + one JSON `data:`
line (`src/mira/core/streaming_sse.py`). The turn source is supervisor-first
when the app was built with an agent-card registry (ADR-014/035): a routed
prompt streams the specialist's recorded `plan_step` events, one `token`
carrying the attributed synthesis, then `done` with a correlation id; an
unmatched prompt falls back to the default runtime turn. Guardrail-out runs
per frame before emission (ADR-037).

### CORS policy

All routes (including the `/turn` SSE response) are served behind a small WSGI
CORS wrapper (`src/mira/core/cors.py`):

- `CORS_ALLOW_ORIGINS` env — comma-separated exact origins. Unset ⇒ default
  policy: any `http://localhost[:PORT]` / `http://127.0.0.1[:PORT]` dev origin.
- Allowed origins get their `Origin` echoed in `Access-Control-Allow-Origin`
  (never `*`), plus `Access-Control-Allow-Methods: GET,POST,OPTIONS`,
  `Access-Control-Allow-Headers: Content-Type`, and `Vary: Origin`.
- `OPTIONS` preflight on a known route answers `204 No Content`.
- Disallowed origins receive no CORS headers; the request is still served — the
  browser enforces the block, the server never rejects on origin alone.

### Server posture

`python -m mira` serves the WSGI app over the stdlib `wsgiref` simple server —
a development server. Selecting a production WSGI server (and the FastAPI
migration this ADR decides) is deferred; the service/app split keeps that swap
a composition-root change only.

### `GET /insights` — advisory insight feed (Phase V3)

`WarmService` routes `GET /insights?domain=<name>` and delegates to an optional
`insights_provider` callable `(domain, refresh) -> dict | None` the composition
root supplies — transport-only, mirroring `/explain`. The report body is the
`InsightReport` contract (`src/mira/orchestration/insights.py`): a plain-dataclass
mirror of the legacy v0 insight shape (summary, observations with
topic/detail/evidence/provenance, suggestions, confidence, caveats,
generated_for). Reports are **advisory only** — suggestions are observations,
never trade instructions, and a fixed disclaimer always lands in `caveats`.

Responses:

| Case | Status / body |
|------|---------------|
| Known domain | `200` — the report dict |
| Provider returns None (unknown domain) | `404 {"error": "unknown_domain"}` |
| Missing `domain` param | `400 {"error": "missing_parameter", "detail": "domain required"}` |
| No provider configured | `503 {"error": "insights_unavailable"}` |

`mira.app.build_app` wires an in-memory `{domain: report}` cache over
`generate_insight_report`: generation is lazy on first request (a scheduled job
hitting the endpoint periodically keeps it warm) and `?refresh=1` regenerates.
Confidence is a deterministic structural heuristic (all battery queries
grounded + error-free → `medium`; any error/ungrounded answer → `low`; `high`
is never produced without a model in the loop). The same report is available
offline via the `mira-insights` console script (`src/mira/insights_cli.py`).
