# State of Memory Lab after M10.3 — Remaining Functionality Inventory

Date: 2026-06-29
Scope: read-only architecture inventory comparing public `context-brain-memory-lab` (`/opt/cbml`) with hosted/private Context Brain (`/opt/contentingestor`) after M10.3 optional semantic enrichment.
Baseline inspected: `/opt/cbml` HEAD `0ad1eafd5de8b4e0e5480cb0a8e6b605b5a8a73e`; approved/pushed milestone commit was `aefcd90acaf68bd82efc940541d6438782ada66b`.

## 1. Current public Memory Lab core

Public Memory Lab is no longer merely an MCP parity scaffold. The current implementation has a modular public-beta core with these proven layers:

- MCP parity surface: 32/32 approved Context Brain-compatible MCP tool names are registered in the public Memory Lab MCP surface, backed by public API/client adapter paths where applicable.
- Workspace-aware API boundary: public routers use `AuthContext`/permission dependencies and route calls through workspace-scoped adapter paths.
- Content persistence: submitted bodies are persisted to `content_chunks` as `chunk_index = 0` through a shared `persist_body_chunks` primitive.
- Content dedup: `content_hash` is stored on `content_items`, with a workspace-scoped partial unique index and friendly API dedup response.
- Deterministic classification: `memory_type`, subtype, confidence, `domain_hint`, and active classification rows are produced without provider dependency.
- Optional semantic enrichment: `topic_tags` and `meta_tags` are stored as provider-neutral semantic annotations. Enrichment is best-effort and never blocks content save.
- Provenance and evidence: retrieval evidence carries chunk ids, retrieval path, score kind, and metadata through canonical normalization.
- Current-state resolution: current-state resolver and classification rules distinguish state/anchor/checkpoint records from ordinary notes.
- Governance substrate: tier routing, governance state, append-only events, tier override/rollback surfaces, and cleanup flows exist in public-beta form.
- Graph layer: hubs, hub links, curated/inferred edges, graph snapshots, graph health, alias hygiene, and hub recall health are present.
- Decisions layer: decision memory, lineage, conflicts, timeline, and status updates are implemented.
- Context/reasoning seams: context-pack builder, deterministic reasoning endpoints, query service, answer synthesizer, intent detector, and policy generator exist.
- Retrieval layer: deterministic chunk text search, hub-linked retrieval, optional pgvector KNN, memory type filtering, and evidence contracts exist.
- Provider posture: OpenAI embeddings and Anthropic LLM adapters are optional/deferred. Empty-env tests remain the baseline.

## 2. Main architectural delta vs private/hosted Context Brain

Private Context Brain still has a mature production ingestion/search stack not fully mirrored in public Memory Lab:

- Hosted/private Context Brain has a more mature `ask_v2`-style query stack, including provider-backed query embeddings, pgvector candidate search, chunk/item fallback, dedup/cleaning behavior, confidence/claims/citations, debug retrieval, and metrics.
- Private ingestion has production-grade extraction helpers including GitHub README fetch, HTML/Jina cleanup, content-signature quality gates, OpenAI embedding generation, chunk embedding backfill, and similarity queries.
- Private scoring/conflict flows include Anthropic-backed ingestion scoring, DB-backed circuit breaker behavior, ANN conflict candidate lookup, LLM conflict classification, and escalation routing.

Public Memory Lab now implements the public-safe substrate for these ideas, but not full private behavior parity. In particular, it favors deterministic fallbacks, provider-neutral contracts, explicit opt-in provider paths, and honest limitations.

## 3. Query-memory behavior parity gap

The most important remaining functionality is query behavior parity, not tool-name parity.

Current public `query_memory` path:

1. `QueryService.execute()` normalizes query and detects intent.
2. It calls `RetrievalAdapter.search()` with workspace scope.
3. Retrieval uses optional pgvector when enabled and configured; otherwise deterministic chunk text and hub-linked results.
4. Results are normalized into evidence, passed through a support-only context pack seam, and synthesized into an `AskResponse`.

Remaining parity work should be treated as behavior slices:

- Retrieval ranking parity: compare private ask_v2 ranking, chunk/item fallback, dedup, hub boost, and confidence thresholds against public retrieval adapter behavior.
- Evidence contract parity: verify citation fields, claim support metadata, insufficient-evidence behavior, and unsupported-intent behavior against private expectations.
- Debuggability parity: public lacks the richer `/ask/debug-retrieval` and `/ask/metrics` surfaces found in private Context Brain.
- Provider boundary parity: public should keep provider calls optional and best-effort, while matching private semantics when pgvector/provider flags are explicitly enabled.
- Test corpus parity: build a small hermetic query fixture set that proves behavior, not just route existence.

## 4. Simplification/consolidation opportunities before M11

Before starting larger query-memory parity work, a short consolidation pass is likely high leverage:

1. Update `docs/CAPABILITIES.md`: it still says the truth map is for M1–M5, while the codebase has advanced through M10.3.
2. Decide whether `memory_lab/query/*` or `memory_lab/reasoning/*` owns canonical AskResponse projection long-term. Recent commits are already extracting canonical seams; finish that boundary before adding more behavior.
3. Keep semantic enrichment contract provider-neutral: public API/storage should continue to say semantic annotations (`topic_tags`, `meta_tags` today), not vendor tags.
4. Preserve save-before-enrich architecture: body save, dedup, classification, and governance must not depend on any provider.
5. Add a single `STATE_OF_MEMORY_LAB` checkpoint document or release note after each major milestone to avoid drifting docs.
6. Consider a minimal private-vs-public parity matrix for query behavior: route/tool, retrieval input, evidence output, confidence logic, provider dependency, and debug surface.

## 5. Recommended next gate

Do not jump straight into broad M11 implementation. Recommended next gate:

`M10.4_STATE_OF_MEMORY_LAB_REVIEW`

Acceptance target:

- This inventory reviewed by human.
- Capabilities/boundaries doc updated to M10.3 reality.
- Query behavior parity slices selected and ordered.
- No new provider dependency introduced into save/ingest path.
- No public contract changed from provider-neutral semantic annotations to vendor-specific semantics.

After that, proceed to a narrow `M11_QUERY_MEMORY_BEHAVIOR_PARITY_RECEIPT` with fixture-first acceptance criteria.
