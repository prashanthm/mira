# ADR-005: Client Surface Boundary

## Status

Accepted
## Context

Mira serves **multiple user-facing entry points** — conversational chat, console/dashboard workflows, portal launchers, and programmatic SDK access — while **all governed data access** flows through the **MCP tool server** tool surface (initiative dependency). This ADR defines which surfaces exist, how each authenticates, and what each is permitted to call.

This is distinct from:

- **Inherited MCP transport** (MCP-server ADR-002) — Streamable HTTP between agent runtime and the MCP tool server.
- **Agent-facing HTTP/WebSocket API** ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)) — contract of the Agent API itself.
- **Phase 1 identity mechanics** ([ADR-033](./adr-033-phase-1-minimum-identity-slice.md)) — how tokens are forwarded and attributed.

Architecture reference: the agent architecture overview in `docs/architecture/`, sections on Agent Chat UI, Analytics Console, and Product Portal integration.

## Decision Drivers

1. **Initiative five-layer model** — "Agent experience" is a distinct layer above agent core and MCP.
2. **Inherited auth** — MCP-server ADR-005: user JWT primary, OAuth2 `client_credentials` for M2M; no API keys.
3. **Product-brief components** — Agent runtime streaming UX, portal, and analytics console are named in the architecture.
4. **Security boundary** — browsers and third-party integrators must not call MCP directly (tool entitlements, rate limits, and audit live at the MCP boundary per MCP-server ADR-022).
5. **Design decision D5** — JWT validation via JWKS; fail-closed.

## Decision

Define **four client surfaces**. Each authenticates via **OIDC/OAuth2** (user or M2M). Each calls only the **Mira Agent API** ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)) — never MCP Streamable HTTP directly.

| Surface | Users | Auth | Permitted calls |
|---------|-------|------|-----------------|
| **Agent Chat UI** | Researchers, analysts, engineers | OIDC user JWT (Entra ID / Okta) | Agent API streaming chat; plan visibility; session management |
| **Analytics Console** | Same + dashboard/reporting workflows | SSO (same IdP) | Agent API; read-only reference-context endpoints (see Boundary Rule 4); domain data queries still via agent→MCP |
| **Product Portal** | Licensed product users | OAuth2/OIDC SSO | Deep links into Chat UI; launcher only — no bypass of agent governance |
| **SDK / typed client** | Integrators, automation | User JWT **or** M2M `client_credentials` | Agent API programmatic endpoints; same entitlements as interactive user |

**Boundary rules:**

1. **Agent API is the sole external API** for clients in Phase 1–2. MCP remains server-to-server (agent runtime → MCP tool server).
2. **Token relay** — Agent API validates inbound JWT ([ADR-033](./adr-033-phase-1-minimum-identity-slice.md)), forwards caller identity to MCP on tool calls (inherited token relay pattern from MCP-server ADR-005).
3. **No browser-to-MCP** — CORS, tool enumeration, and entitlements are not exposed to browsers.
4. **Analytics Console read-only services** — limited to **static rendering assets** and **non-domain reference context** (e.g. schema metadata, dataset catalogs). These are the only non-Agent-API calls any surface may make; the concrete service list is owned by the MIRA-RUNTIME foundation-arch spec and amended there, not enumerated here. Any domain **data query** (e.g. a `docs.search` lookup or `ledger.query` aggregation) routes through agent orchestration (agent→MCP).
5. **SDK security & versioning** — SDK consumers authenticate via the standard OAuth2 flows defined in the inherited MCP-server ADR-005 (user JWT primary; `client_credentials` for M2M) — no SDK-specific auth path. SDK versioning follows Agent API versioning ([ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md)); breaking changes require a major API version bump, communicated through the Agent API changelog and the SDK's release notes.

> **Product Portal deep-link contract:** the Portal row is a *display/launcher* surface — the Portal opens a Chat UI URL under the user's existing SSO session and does not mint or forward a separate session token. Whether the Portal ever becomes an *integration* surface (forwarding tokens) is out of scope here; the deep-link contract detail is finalized in the MIRA-RUNTIME feature spec.

**Rejected alternatives:**

- **Expose MCP Streamable HTTP to browsers** — Rejected: expands attack surface; bypasses agent middleware (guardrails, correlation, cost attribution); entitlements model assumes server-side caller.
- **API keys for SDK clients** — Rejected: inherited MCP-server ADR-005 rejects keys (no expiry/rotation; breaks per-user source-platform ACL audit).
- **Single surface (chat only)** — Rejected: product-brief and architecture commit to portal and console workflows; deferring console/portal creates duplicate integration paths later.
- **Per-surface MCP credentials** — Rejected: multiplies secret sprawl; contradicts the OIDC-only, user-JWT-primary posture.

## Validation

This is a boundary-defining ADR, not an implementation; the surfaces themselves are built under MIRA-RUNTIME. The boundary holds if each surface, once implemented, satisfies:

1. **Single external API** — every surface's network traffic terminates at the Agent API; no client issues a request directly to MCP Streamable HTTP (verifiable by inspecting CORS allow-lists and the absence of MCP endpoints in client config).
2. **JWT fail-closed** — requests without a valid JWKS-verified JWT are rejected with 401 at the Agent API edge (inherited from MCP-server ADR-005 / design decision D5).
3. **Analytics Console scope** — the Analytics Console's only non-Agent-API calls are the read-only services in Boundary Rule 4; any domain data path routes through agent orchestration.
4. **SDK entitlements parity** — an SDK caller receives exactly the source-platform entitlements of its underlying identity, with no surface-specific elevation.

Surface-level conformance tests are specified in the MIRA-RUNTIME feature spec; this ADR sets the criteria they assert against.

## Consequences

### Becomes Easier

- One external security review scope (Agent API + auth).
- Clear diagram: Client → Agent API → MCP → sources.
- Portal and chat share session/auth infrastructure.

### Becomes Harder

- Analytics Console requires coordinated releases with Agent API contract.
- SDK consumers must implement OAuth2 flows, not static tokens.
- Every new client surface needs explicit row in this ADR (amendment, not ad-hoc endpoint).

## Applies To

- **MIRA-RUNTIME** — Agent API implementation
- **MIRA-AGENTS** — chat UX (Phase 2)
- [ADR-006](./adr-006-api-design-standard-for-agent-facing-interfaces.md) — API contract
- [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — Phase 1 auth forwarding
- [ADR-034](./adr-034-per-agent-identity-and-task-scoped-tokens.md) — per-agent identity (Phase 2, supersedes slice for specialists)
- Inherited: MCP-server ADR-005 (authentication strategy), MCP-server ADR-022 (entitlements enforcement model)

## Links

- ADR file: `docs/adr/adr-005-client-surface-boundary.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-005
- Architecture: `docs/architecture/` (agent architecture overview)
