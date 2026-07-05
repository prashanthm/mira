# ADR-018: Memory Integrity & Embedding Versioning

## Status

Accepted

## Context

[ADR-017](./adr-017-memory-architecture.md) (Accepted) fixed the three-tier memory model — working
(in-context graph state), session (LangGraph checkpointer behind `IStateStore`), and long-term
(a framework-agnostic retrievable store of summaries/embeddings behind the
[ADR-002](./adr-002-provider-abstraction-pattern.md) seams) — and explicitly deferred **"memory-poisoning
protection and embedding-version pinning (OWASP LLM03/LLM08)"** to this ADR. [ADR-021](./adr-021-storage-engine-selection.md)
(Accepted) subsequently fixed the vector index as a storage *role* behind those same seams, with the
concrete engine (pgvector on-prem, managed vector DB or OpenSearch cloud) as a per-profile default,
not an architectural commitment. This ADR does not re-open either of those decisions; it decides the
two things ADR-017 left open for the long-term tier: how writes into that store are protected against
poisoning, and how stored embeddings stay valid and comparable when the embedding model changes.

Both are live, demonstrated risks, not speculative ones. OWASP's 2025 LLM Top 10 (LLM08, Vector and
Embedding Weaknesses) and the emerging Agentic AI Top 10 (ASI06, Memory & Context Poisoning) both
name persistent agent memory as a distinct attack surface. Two NeurIPS papers demonstrate the attack
in practice: AgentPoison (2024) achieves ≥80% attack success at <0.1% poison rate against RAG-agent
memory with no model retraining, and MINJA (2025) injects malicious memory records through ordinary
query-only interaction — no elevated privilege required. Separately, production vector-database
vendors document that embeddings from different model versions are not comparable, and that mixing
them in one index silently degrades retrieval quality ("index drift") with no obvious failure signal.

## Decision Drivers

1. **ADR-017 deferred scope** — this ADR is the named home for memory-poisoning protection and
   embedding-version pinning; ADR-017 fixed tiering/seams only.
2. **Demonstrated write-path attacks** — AgentPoison and MINJA both succeed via the ordinary
   write/retrieval path, not privilege escalation; retrieval-time-only controls do not catch them.
2a. **ADR-021 seam discipline** — the mechanism must live at the `IStateStore`/`IObjectStore` metadata
   layer, not couple to a specific vector-DB vendor (would break ADR-021 "engine as per-profile
   default" and ADR-047 on-prem portability).
3. **Vendor-documented index-drift failure mode** — mixed-version embeddings in one index are
   silently wrong; the vendor-recommended fix is version-tagging plus alias-based re-embedding, not
   ad hoc in-place upgrades.
4. **Regulated, auditable setting** — the same NIST/OWASP posture already driving ADR-017/ADR-037
   requires provenance and auditability on what enters long-term memory.

## Research & Rubric

`Research & rubric — ADR-018`.
Scored write-time provenance + trust-gated ingestion with version-tagged/alias-swapped re-embedding
vs. retrieval-time-only filtering with untagged re-embedding vs. a managed vendor "trusted RAG"
product, against poisoning-lifecycle coverage, resistance to the published AgentPoison/MINJA attacks,
mixed-version retrieval safety, rollback, ADR-002/021 seam fit, and implementation cost. The write-time
provenance + version-tagged option wins on every dimension except raw implementation cost. Self-contained
on OWASP LLM08/ASI06, two NeurIPS memory-poisoning papers, a 2026 memory-security survey, and Qdrant/Pinecone
vendor documentation for embedding-version migration; internal ADRs (017, 021, 002) fix the seams this
attaches to.

## Decision

Adopt **write-time provenance with trust-gated ingestion** for long-term memory integrity, and
**version-tagged embeddings behind a stable alias with parallel-index re-embedding** for embedding
consistency across model upgrades. Both are metadata/process controls at the ADR-002 storage seam —
neither fixes a vector-DB vendor.

**1. Poisoning defense (write-time, not retrieval-only)**

- Every long-term-memory write carries a **provenance record**: source (tool result, user turn,
  another agent's synthesis), actor/attribution ([ADR-033](./adr-033-phase-1-minimum-identity-slice.md)-style
  identity), timestamp, and a trust tier.
- Writes pass a **trust gate before storage** — low-trust or unverified content (e.g. raw user free
  text asserting a fact with no corroborating tool/source) is stored at a lower trust tier or held for
  review rather than admitted at full trust by default. Concrete trust-tier thresholds are a
  MIRA-MEMORY spec decision, not fixed here.
- Retrieval is **provenance-aware**: the retrieval layer can down-weight or exclude low-trust records
  rather than treating everything in the store as equally authoritative.
- Long-term-memory writes and retrievals are **logged immutably** for audit, consistent with the
  ADR-017 tenant-scoping requirement and the existing NIST/OWASP posture ([ADR-037](./adr-037-bidirectional-guardrail-pipeline.md)).
- This is deliberately a **write-time** control, not solely an output-side guardrail — the literature
  and the two published attacks this ADR is grounded in both enter through the write path.

**2. Embedding-version consistency**

- Every stored embedding is **tagged with the embedding-model identifier/version** at write time.
- The long-term store is addressed through a **stable pointer** (alias / version-scoped collection) so
  application code never depends on a specific embedding-model version directly.
- On an embedding-model upgrade, re-embed via a **parallel-index-then-swap migration**: build the new
  version's index alongside the old, validate retrieval quality, then atomically swap the pointer.
  The old version stays available for **instant rollback** until the new version is confirmed healthy.
- **Vectors from different embedding-model versions are never queried together in the same
  similarity search** — this is the specific, vendor-documented failure mode ("index drift") this
  decision exists to prevent.
- This is expressed as a **data-model and process requirement at the ADR-002 seam** (version metadata
  + pointer-swap semantics), so it holds regardless of which ADR-021 vector-index engine a profile
  uses (pgvector on-prem, managed vector DB or OpenSearch cloud).

**Rejected alternatives:**

- **Retrieval-time-only filtering, untagged re-embedding** — Rejected: covers only the Execute/output
  phase of the memory lifecycle; both AgentPoison and MINJA succeed via the write path this leaves
  open. Untagged re-embedding also risks silently mixing incompatible vector versions in one index,
  the exact index-drift failure mode vendor documentation warns against.
- **Managed vendor "trusted RAG" product** — Rejected: couples the architecture to one vendor's
  proprietary poisoning defense and re-indexing implementation, contradicting ADR-021's "engine as
  per-profile default, not architectural commitment" and ADR-047 on-prem/portability; effectiveness
  against the specific published attacks this ADR is grounded in is unverified.

## Consequences

### Becomes Easier

- Long-term memory has a defined, literature-grounded defense against demonstrated poisoning attacks
  (AgentPoison, MINJA) rather than relying solely on output-side guardrails.
- Embedding-model upgrades become a safe, reversible operation (parallel index + alias swap with
  instant rollback) instead of an ad hoc in-place migration risking silent retrieval-quality loss.
- Provenance metadata gives auditors a traceable answer to "why did the agent believe this" for
  anything sourced from long-term memory.
- The mechanism is engine-agnostic — it composes with whatever ADR-021 vector-index engine a
  deployment profile selects, with no vendor lock-in.

### Becomes Harder

- Every long-term-memory write now carries provenance/trust-tier metadata and passes a gate —
  more moving parts than accepting all writes uniformly, and a source of latency/complexity in the
  write path.
- Embedding-model upgrades require holding two vector versions during migration (storage/compute
  cost) and a validation step before the pointer swap, rather than upgrading in place.
- Trust-tier policy (what counts as "trusted" for a given write) is a nontrivial, ongoing
  classification problem that this ADR does not fully specify — it is deferred to the MIRA-MEMORY spec.
- No defense here has been adversarially validated against AgentPoison/MINJA-style attacks in this
  codebase yet — effectiveness is a claim from the literature until eval/red-team coverage confirms it.

## Applies To

- **MIRA-MEMORY** — long-term memory tier integrity and embedding versioning (primary)
- [ADR-017](./adr-017-memory-architecture.md) — three-tier memory model this ADR completes (deferred scope)
- [ADR-021](./adr-021-storage-engine-selection.md) — vector-index storage role this attaches metadata to
- [ADR-002](./adr-002-provider-abstraction-pattern.md) — `IStateStore`/`IObjectStore` seams carrying the provenance/version metadata
- [ADR-033](./adr-033-phase-1-minimum-identity-slice.md) — attribution identity backing provenance records
- [ADR-037](./adr-037-bidirectional-guardrail-pipeline.md) — complementary output-side guardrail (this ADR adds write-time coverage)
- [ADR-045](./adr-045-eval-framework-ci-safety-gate.md) — candidate home for adversarial (poisoning) eval coverage of this defense

## Links

- ADR file: `docs/adr/adr-018-memory-integrity-and-embedding-versioning.md`
- Research & rubric: `research/adr-018-memory-integrity-and-embedding-versioning.md`
- Catalog: [adr-list.md](./adr-list.md) — ADR-018
- Epic: MIRA-MEMORY
