# ADR-033: Phase 1 Minimum Identity Slice

## Status

Accepted

## Context

The initiative splits identity into **Phase 1 minimum slice** (service identity + per-call attribution + MCP-scoped entitlements) and **Phase 2 full per-agent model** (**MIRA-IDENTITY**, ADR-034/035). Client surfaces ([ADR-005](./adr-005-client-surface-boundary.md)) authenticate users via OIDC; the agent runtime must **forward identity to MCP** without re-implementing entitlements (inherited MCP-server ADR-022 — entitlements enforcement model).

Auth **mechanics** (JWT vs M2M, JWKS validation) are inherited from MCP-server ADR-005/007. This ADR records **what Mira adds** at Phase 1 — not a new auth protocol.

OpenSpec **D5**: PyJWT + cached JWKS, fail-closed validation.

## Decision Drivers

1. **Initiative success criterion** — "Phase 1 ships a minimum identity slice … Phase 2 (MIRA-IDENTITY) delivers full per-agent identity."
2. **Inherited entitlements boundary** — MCP owns tool/data access enforcement; Mira adds task-scope narrowing in Phase 2 only.
3. **Pilot-ready agents criterion** — "observable calls (tenant, user, correlation)" on MCP tool surface.
4. **PoC gap** — weak or absent JWT verification in evaluation; Phase 1 must fail closed.
5. **ADR-005/006** — Agent API validates inbound tokens before any orchestration or MCP call.

## Decision

Phase 1 implements a **single service identity** for the agent runtime with **per-request caller attribution** forwarded to MCP.

**Components:**

1. **Inbound validation (Agent API middleware)**
   - Validate `Authorization: Bearer <JWT>` via remote JWKS (1-hour cache, refresh on unknown `kid`) — same contract as MCP-server ADR-007 (JWT validation approach).
   - Enforce `exp`, `aud`, `iss` claims; reject on any failure — **no anonymous access** except `/health` and `local` profile with explicit `skip_auth=true` (development only, blocked in `saas` profile per ADR-047).
   - **Invalid / expired / malformed JWT** → fail closed with `401` and `WWW-Authenticate: Bearer error="invalid_token"`; **never** return claim contents or validation internals to the client. Log the rejection at `warning` with `error_reason` (e.g. `expired`, `bad_signature`, `missing_aud`), `iss`, `kid`, and `correlation_id` — **never** the raw token or its decoded claims.

2. **Attribution context (per request)**
   - Extract and bind to structlog + OTel span:
     - `tenant_id` — from claim or gateway header (multi-tenant SaaS profile)
     - `user_id` — JWT `sub`
     - `correlation_id` — from `X-Correlation-ID` or generated; **forward to MCP, do not regenerate** (inherited MCP-server ADR-012 — correlation-ID propagation). **Missing or malformed** inbound `X-Correlation-ID` (absent, empty, or not a valid UUID) → generate a fresh UUIDv4, bind it for the rest of the request, and emit it on the response `X-Correlation-ID` header; the request **never** fails on correlation-id alone. A present-and-valid value is preserved end-to-end unchanged.
   - Optional `client_id` for M2M flows (`client_credentials`).

3. **MCP token relay**
   - Forward the **caller's user JWT** (or service token obtained via authorized M2M on behalf of user) to MCP Streamable HTTP requests.
   - Agent runtime does **not** implement source-platform entitlements lookups — relies on MCP-server ADR-022.
   - **Observability:** every relay emits a structlog event + OTel span attribute carrying `tenant_id`, `user_id`, `correlation_id`, MCP tool name, and outcome (`relayed` / `rejected_401` / `token_expired`) — **never** the token itself. A `401` from MCP is logged at `warning` and surfaced to the caller unmodified; relay rejections are countable for alerting. This is the relay-side complement to the inbound-validation logging in Component §1.

   **Token expiry mid-orchestration (Phase 1 policy).** Phase 1 takes the **fail-fast** default: if the relayed token's `exp` passes during a long-running orchestration or stream, the next MCP call fails with `401` and `WWW-Authenticate: Bearer error="invalid_token"` and the orchestration step returns that `401` to the caller — **no in-flight token refresh** in Phase 1. Refresh-token round-trips are deferred to ADR-006's API spec and the Phase-2 per-agent token model (ADR-034), where task-scoped tokens make scoped re-issue tractable. Rationale: in-flight refresh requires holding refresh credentials in the runtime, which conflicts with the Phase-1 single-service-identity boundary.

4. **Service identity**
   - One IAM/runtime identity for the agent container (ECS task role / K8s SA) for **platform** calls (model calls via `ILLMProvider`, secrets via `ISecretsProvider`).
   - Distinct from **end-user identity** carried in JWT — both appear in audit logs with clear labels.

   **`skip_auth` containment rule (Phase 1).** `skip_auth=true` is honored **only** in the `local` profile. Any non-`local` profile (`saas`, `outposts`) **fails fast at startup** if `skip_auth` is set — the process refuses to boot rather than serving with auth disabled. This is a startup invariant of the Agent API, not a runtime check, so a `.env.local` accidentally promoted into a production image is caught before the first request. The full validation-warning taxonomy (warn vs fail-fast across all profile flags) is the subject of **ADR-047 (profile validation warnings)**, which is **not yet authored** — see [adr-list.md](./adr-list.md). Stating the `skip_auth` rule here ensures the Phase-1 invariant is binding even before ADR-047 lands; ADR-047 will generalize it, not introduce it. **Verification of this invariant** (startup-refusal test on `saas`/`outposts` + a CI guard that the production image build sets no `skip_auth`) is captured as a Phase-1 implementation acceptance criterion on the MIRA-ARCH middleware work, not re-specified per-ADR.

5. **Phase 2 deferrals (explicitly out of scope Phase 1)**
   - Per-agent identities, task-scoped tokens (ADR-034)
   - Agent cards / A2A discovery (ADR-035)
   - Prompt-injection defense pipeline (ADR-036)

**Rejected alternatives:**

- **M2M-only service account for all users** — Rejected: inherited MCP-server ADR-005; collapses per-user source-platform ACLs and audit trail.
- **Full per-agent tokens in Phase 1** — Rejected: roadmap and success criteria explicitly defer to MIRA-IDENTITY; premature complexity before supervisor routing exists.
- **Re-implement entitlements in agent runtime** — Rejected: duplicates MCP-server ADR-022; violates the Depends-On MCP-server boundary.
- **API keys for agent API** — Rejected: inconsistent with inherited JWT-primary model and ADR-005 client boundary.

## Consequences

### Becomes Easier

- Phase 1 delivery bounded — one middleware auth module, one token forward path.
- End-to-end audit: user → agent span → MCP span with shared correlation ID.
- Clear upgrade path to ADR-034 without breaking client surfaces.

### Becomes Harder

- All specialists share one service identity until Phase 2 — cannot prove per-agent least-privilege in Phase 1 audits (documented limitation).
- Token expiry mid-orchestration is resolved fail-fast for Phase 1 (`401`, no in-flight refresh — see Component §3); long-running streams that outlive `exp` will surface a `401` to the caller rather than transparently continuing. In-flight refresh is deferred to ADR-006 / Phase 2 (ADR-034).
- `skip_auth` in local profile must never leak to production profiles — enforced by the Component §4 startup-refusal invariant on non-`local` profiles; the general profile-validation taxonomy is deferred to ADR-047 (not yet authored).

## Applies To

- **MIRA-ARCH** — middleware implementation
- **MIRA-RUNTIME** — request lifecycle
- **MIRA-CONNECTORS** — MCP client calls with forwarded tokens
- [ADR-005](./adr-005-client-surface-boundary.md), [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md), [ADR-009](./adr-list.md)
- Phase 2: **MIRA-IDENTITY**, [ADR-034](./adr-list.md), [ADR-035](./adr-list.md)
- Inherited: MCP-server ADR-005 (authentication strategy — M2M and user tokens), ADR-007 (JWT validation approach), ADR-010 (authorization granularity), ADR-022 (entitlements enforcement model)

## Links

- ADR file: `docs/adr/adr-033-phase-1-minimum-identity-slice.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-033
- OpenSpec D5: auth spec (`openspec/changes/ai-agent-production-hardening/specs/auth/spec.md`)
