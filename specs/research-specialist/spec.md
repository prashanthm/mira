# Research Specialist Subgraph — Spec

> **Feature slug:** research-specialist
> Siblings: [`plan.md`](./plan.md) (files/steps/ADRs/edge-cases) · [`tasks.md`](./tasks.md) (granular units + Loop AC)

## Behavior / What

Deliver the **research domain specialist** — the first demo domain of the Mira reference
implementation — as a **state-isolated LangGraph subgraph** running the ADR-013 ReAct
reasoning loop (`plan → act → observe → reflect`) by instantiating the shared
specialist-subgraph scaffold. It answers questions over a Markdown document corpus via
the **docs connector**: front-matter + `##` sections parsed into the uniform connector
shape, published as typed MCP tools (`docs.sections`, `docs.search`) with fail-closed
entitlements, and grounded through the federation fabric with citable section-anchor
provenance.

### Observable behaviors

1. **Connector** — `mira.connectors.docs` parses Markdown (front-matter headers +
   `##` sections) into `DocsDocument`; malformed input raises `DocsParseError`.
2. **Uniform shape** — `DocsConnector.query({"query": term})` returns `SourceRecord`s
   whose `Provenance.source_id` carries a `#<anchor>` citation.
3. **Typed MCP surface** — `export_tools()` publishes `docs.sections` / `docs.search`
   as ADR-031 `ToolContract`s (flat schema, `connector:docs:*` entitlements, read-only).
4. **Grounded federation** — `fabric.federation.query()` over the connector returns an
   attributed `FederatedQueryResult` (ADR-019 query-in-place).
5. **Specialist** — `build_research_specialist()` wraps `RESEARCH_DOMAIN`
   (`domain_id="research"`, prefix `docs.`) with a per-domain `query_inference` hook;
   the representative handbook question returns the middleware-ordering section with
   provenance, in the supervisor-consumable `SpecialistResult` shape.

## Acceptance Criteria

- [x] Docs connector parses front-matter + sections and rejects malformed documents
- [x] Connector conforms to `SourceConnector`; records carry anchor provenance
- [x] `docs.*` tools export as typed, read-only, entitlement-bearing contracts
- [x] Federation query returns an attributed, citable answer
- [x] `REPRESENTATIVE_RESEARCH_QUERY` runs end-to-end through the specialist
- [x] Import isolation lint and full offline test suite pass
