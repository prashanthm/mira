# Extending Mira to a New Use Case

Mira is domain-agnostic by construction: a new use case is a **domain** — a source
connector, a typed MCP tool surface, and a specialist subgraph — registered against
seams the core already provides. Nothing in `core/`, `model/`, `fabric/`, or the
scaffold changes. This walkthrough follows the two in-tree demo domains (`research`
over `connectors/docs.py`, `finance` over `connectors/ledger.py`); mirror whichever
is closer to your source's shape.

## The five steps

### 1. Write a connector (`src/mira/connectors/<source>.py`)

Implement the `SourceConnector` protocol (`connectors/base.py`): an anti-corruption
adapter that translates your source into the uniform record shape.

- Parse/adapt the source **dependency-free** — vendor SDKs belong in `providers/`
  (ADR-002); the import linter enforces this.
- Return `SourceRecord`s carrying `Provenance` (source attribution + units or
  reference-frame). Put the *denomination* of an answer in provenance — the ledger
  connector carries the currency as `Provenance.units`, the docs connector carries a
  citable `#section-anchor` in `source_id` — so grounding attributes a qualified
  answer, never a bare number (ADR-020, ADR-025).
- Expose `connector_id` / `source_name` properties so the federation fabric can
  attribute query-in-place answers (ADR-019).
- Fail loudly on malformed input or empty matches with a domain `ParseError`; never
  return a silent empty answer.

### 2. Declare the tool surface (`tool_specs()`)

Implement `tool_specs()` returning `ToolSpec`s (`connectors/mcp_export.py`), one per
operation. `export_tools(connector)` turns them into typed `ToolContract`s (ADR-031):
flat JSON-schema inputs, behavior annotations, and a **fail-closed
`required_entitlement`** (`connector:<source>:<capability>`). Name tools with your
domain prefix — `docs.search`, `ledger.query` — the prefix is the allow-list key.

### 3. Declare the domain (`orchestration/specialists/domains.py`)

```python
ANALYTICS_DOMAIN = DomainSpec(
    domain_id="analytics",
    tool_prefixes=frozenset({"metrics."}),
)
```

The `DomainSpec` is the whole domain identity: its id namespaces checkpointer threads
(state isolation between domains, ADR-014), and its prefixes scope which tools the
specialist may bind (fail-closed — an empty allow-list binds nothing).

### 4. Build the specialist (`orchestration/specialists/<domain>.py`)

~25 lines, mirroring `specialists/finance.py`:

```python
def build_analytics_specialist(tools, *, budget=None):
    return build_specialist_subgraph(
        ANALYTICS_DOMAIN,
        tools,
        budget=budget,                      # ReasoningBudget: steps/tokens/time/cost
        query_inference=_infer_metrics_query,  # optional per-domain hook
    )
```

`build_specialist_subgraph` wraps the shared ADR-013 ReAct loop — no new LangGraph
wiring; the `finance` domain was added to prove exactly this. `query_inference` is an
optional hook mapping the loop's `act:` strings to a tool call; without it,
non-explicit actions fall through to a structured noop (the explicit
`act:tool:<name>:<json>` channel always works). The specialist returns a
`SpecialistResult` — the contract the supervisor consumes.

### 5. Export, test, spec

- Re-export from `specialists/__init__.py` and `orchestration/__init__.py`.
- Add a fixture under `tests/fixtures/` and two test files mirroring
  `test_ledger_connector.py` + `test_finance_specialist.py`: parse, protocol
  conformance, typed MCP export, federation grounding, representative query
  end-to-end, cross-domain tool invisibility. All offline.
- Record intent in `specs/<domain>-specialist/{spec,plan,tasks}.md` (see
  `specs/finance-specialist/` for the worked example).

## If your source needs a real backend

Wire live sources through an **MCP server** instead of an in-process handler: declare
it via `MCP_SERVERS` env JSON (or `MCP_BASE_URL` shorthand) and the runtime discovers
its tools at boot (`connectors/mcp_registry.py`, `orchestration/mcp_tools.py`).
Discovery failures degrade to zero-MCP rather than failing boot. Cloud SDKs go behind
a provider in `providers/` — never in the connector.

## Wrapping a foreign agent (ADR-051)

A domain does not have to be a Mira specialist. Any agent that implements the
`mira_contracts.agent.EnvelopeRunner` Protocol (`card()`, `run(envelope) -> TraceResult`) can be
registered as a routable specialist:

- Implement the runner against `mira_contracts` only — the ExecutionEnvelope carries the
  objective, tool grants, budget, and constraints; the TraceResult must carry
  provenance-attributed answers and `plan_step` events to pass the eval gate.
- Wrap it with `mira.orchestration.foreign.ForeignSpecialist` and register via
  `foreign_card(...)` + `registry.register` — the supervisor is untouched. Policy-in,
  envelope/trace validation, and cost attribution are applied by the wrapper, fail-closed.
- For an out-of-process agent, use `mira_harness.cli_adapter.CliAgentAdapter` (envelope JSON on
  stdin → trace JSON on stdout, timeout-bounded) and set `FOREIGN_AGENT_CMD`.
- Add golden cases under `evals/goldens/` — foreign specialists are held to the same
  trace-score bar and gate promotions like natives.

## Checklist

- [ ] `make lint` (import boundaries + sanitize-check) passes
- [ ] `make test` passes offline — no network, no credentials
- [ ] Provenance carries the answer's denomination/citation
- [ ] Entitlements declared on every tool (fail-closed)
- [ ] Representative query runs end-to-end via the specialist
- [ ] Spec trio recorded under `specs/`
