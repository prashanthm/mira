# ADR-017: Memory Architecture

## Status

Accepted

## Context

The product brief commits MIRA-MEMORY to "session + long-term memory, summarization" so "context
persists across sessions." [ADR-007](./adr-007-core-agent-stack-and-framework.md) selects LangGraph,
whose **checkpointer** persists thread-scoped state and enables the durable resume the framework was
chosen for; [ADR-002](./adr-002-provider-abstraction-pattern.md) fixes `IStateStore` (session/durable
KV) and `IObjectStore` as the storage seams. This ADR decides the memory tiers, where each is stored,
and how context is compressed — without coupling long-term memory to the framework (ADR-007
containment), and leaving memory-integrity/embedding-versioning to [ADR-018 (Proposed)](./adr-list.md).

## Decision Drivers

1. **MIRA-MEMORY** — session + long-term memory with summarization; context persists across sessions.
2. **ADR-007 durable resume** — session state must survive pauses/deploys (checkpointer).
3. **ADR-002 storage isolation** — memory stores sit behind `IStateStore`/`IObjectStore`, no vendor coupling.
4. **ADR-007 containment** — long-term memory/retrieval must not be framework-coupled.
5. **Long-horizon recall + cost** — compression keeps long conversations within context/cost bounds
   (MemGPT / Generative Agents pattern).

## Research & Rubric

`Research & rubric — ADR-017`. Scored three-tier-with-checkpointer-behind-`IStateStore` vs a single store vs framework-native-memory-for-everything against the committed tiering, session resume, long-horizon recall/compression, storage isolation, and ADR-007 containment. The three-tier model wins — checkpointer for durable session state, a framework-agnostic retrievable long-term store behind the ADR-002 seams, and summarization-based compression. Self-contained on LangGraph persistence docs, MemGPT/Generative-Agents papers, OWASP/NIST; internal ADRs fix the seams.

## Decision

Adopt a **three-tier memory architecture**:

| Tier | Contents | Storage |
|------|----------|---------|
| **Working** | In-context state for the current reasoning run (graph state) | LangGraph graph state (in-context) |
| **Session** | Durable, resumable conversation state across turns/pauses | **LangGraph checkpointer behind `IStateStore`** ([ADR-002](./adr-002-provider-abstraction-pattern.md)) — in-memory/SQLite local, Postgres/DynamoDB SaaS, per profile |
| **Long-term** | Cross-session knowledge: summaries + embeddings, retrievable | A **framework-agnostic retrievable store** behind `IStateStore`/`IObjectStore`; retrieval is not LangChain-coupled |

- **Context compression:** when the working/session context approaches a token threshold, summarize
  older turns (Generative-Agents-style) and page detail to long-term — keeping the live context
  within bounds without losing recall. The MIRA-MEMORY spec should define a **compression safety
  floor** (minimum lookback window that summarization never collapses) to prevent the
  "summarization swallowed the bug-repro context" failure mode.
- **Long-term store backend:** the specific vector/retrieval backend is **not decided here** — it is
  implementation detail behind `IStateStore`/`IObjectStore`. The deciding ADR is [ADR-018 (Proposed)](./adr-list.md)
  (memory integrity & embedding versioning), which is the natural home for backend selection given
  its overlap with embedding-version pinning. If a separate storage-engine ADR is introduced, its
  number should be recorded here.
- **Containment ([ADR-007](./adr-007-core-agent-stack-and-framework.md)):** the checkpointer is used
  via the orchestration layer; long-term memory and embedding/retrieval live behind the ADR-002
  Protocols, **not** in framework-native memory abstractions, so retrieval survives a framework change.
- **Tenant scoping:** every tier is scoped by the attribution context (`tenant_id`/`user_id`,
  [ADR-009 (Proposed)](./adr-list.md)/[ADR-033](./adr-033-phase-1-minimum-identity-slice.md)).
- **Out of scope (→ [ADR-018 (Proposed)](./adr-list.md)):** memory-poisoning protection and embedding-version
  pinning (OWASP LLM03/LLM08) are a separate ADR; this one fixes tiering + storage seams.

**Rejected alternatives:**

- **Single durable store, no tiers** — Rejected: no compression strategy, poor long-horizon recall,
  loses the checkpointer's resume semantics.
- **Framework-native memory for everything** — Rejected: pulls long-term memory + embeddings into the
  framework layer against ADR-007 containment and couples retrieval to LangChain.
- **No long-term tier (session only)** — Rejected: fails "context persists across sessions" (MIRA-MEMORY).

## Consequences

### Becomes Easier

- Durable, resumable sessions come from the checkpointer ADR-007 already relies on.
- Long-term recall + compression keep long conversations within context/cost bounds.
- Storage is swappable per deployment profile behind `IStateStore`/`IObjectStore`.
- Long-term memory stays framework-agnostic — survives a framework change.

### Becomes Harder

- Three tiers + compression is more moving parts than a single store; summarization fidelity needs tuning.
- The checkpointer backend and the long-term store are now operational dependencies per profile.
- Tenant isolation must be enforced across all tiers.

## Applies To

- **MIRA-MEMORY** — layered memory (primary)
- **MIRA-REASON** — working memory is the reasoning graph state
- [ADR-007](./adr-007-core-agent-stack-and-framework.md) — checkpointer + containment
- [ADR-002](./adr-002-provider-abstraction-pattern.md) — `IStateStore`/`IObjectStore` seams
- [ADR-018 (Proposed)](./adr-list.md) — memory integrity & embedding versioning (separate ADR)
- [ADR-009 (Proposed)](./adr-list.md) / [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — tenant/attribution scoping

## Links

- ADR file: `docs/adr/adr-017-memory-architecture.md`
- Research & rubric: `research/adr-017-memory-architecture.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-017
