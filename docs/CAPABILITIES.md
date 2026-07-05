# Public capabilities and boundaries

Current package version: `1.0.0`.

This document is the compact truth map for Memory Lab v1.0 — feature-complete
and closed against the full-provider field-validation cycle (FV-1..FV-9,
2026-07-04/05). It supersedes older B-era and M-era wording. For the ratified
architecture boundaries (standing doctrines, graph authority model, Graph
Navigation scope freeze, v1.0 exception policy), see
[ARCHITECTURE_BOUNDARIES.md](ARCHITECTURE_BOUNDARIES.md) — accepted
limitations and vNext items live there and in the CHANGELOG, deliberately
separated from blockers.

## Implemented and proven

- **Deterministic empty-env core** — imports, deterministic helpers, and hermetic tests run without provider keys, without private Context Brain access, and without a configured database.
- **Workspace-aware API and retrieval surfaces** — FastAPI routers and evidence contracts remain public-beta and self-hosted.
- **MCP parity surface** — 32/32 approved Context Brain-compatible MCP tool names are registered in the public Memory Lab MCP surface.
- **Content body persistence** — created content bodies are persisted to `content_chunks` through a shared body persistence primitive.
- **Workspace-scoped content dedup** — content creation computes `content_hash` and uses a workspace-scoped unique index/friendly duplicate response when Postgres persistence is configured.
- **Deterministic classification and current-state substrate** — public classification/current-state logic remains provider-free and does not claim semantic truth understanding. Scope resolution is a deterministic pipeline (explicit `scope_hint` → in-text marker → anchor lineage → hub alias match → classify metadata → keyword heuristic → `global` last resort) with the winning tier reported as `current_state_scope_source`. When the classify-confidence gate skips the resolver, the save response says so (`current_state_status: noop`, `current_state_reason: low_confidence`) instead of staying silent.
- **Current-state visible on direct reads** — GET content/metadata (and the MCP content-get tool) expose `is_current`, `current_state_scope`, and `cs_supersedes_content_id` through one canonical projection; ranked raw search deliberately stays physics-only.
- **Loud empty-save failure** — POST /v1/content with missing/empty content returns 422 (batch: inline per-item failure); an empty save never reports `persisted: true`.
- **Conflict escalations with a human gate** — ingest-path conflict detection produces escalations reviewed via approve/reject; contradictions are surfaced, never auto-resolved.
- **Deterministic edge inference with a human gate** — provider-free co-membership/tag-alignment signals propose hub edges as `status=inferred`; only human approval promotes them, and rejections are never silently resurrected.
- **Evidence-grounded ask with current-state awareness** — /v1/ask enriches retrieved evidence with resolver-owned current-state fields; a superseded item is demoted below the current item of the same scope (historical questions keep original order), with explicit ranking reasons.
- **Reasoning traverse/explain with honored max_hops** — hop-bounded BFS query expansion consults the curated hub graph through read-only hub-term adjacency (reasoning surface only), and traversal steps expose hub/graph provenance.
- **MCP ergonomics** — all 32 approved MCP tools ship useful descriptions; `query_memory` can opt into the provider-backed ask mode and self-explains when the deployment gate keeps it deterministic.
- **Optional semantic annotations** — `topic_tags` and `meta_tags` can be produced as provider-neutral, best-effort enrichment; save/ingest success does not depend on provider availability.
- **Canonical query/evidence seams + opt-in grounded answer** — public query paths normalize evidence, project `AskResponse` through canonical seams, declare a `mode` (`deterministic|provider_backed|degraded`), and accept optional `memory_type`/`memory_types` filters. When explicitly opted in per request and enabled by deployment config, the answer is provider-backed wording bounded to retrieved evidence, enforced by a citation allow-list (no invented citations) and a typed degraded fallback. This is bounded evidence-grounded wording, not private `ask_v2` ranking/confidence parity.
- **Decision, graph, governance, context-pack, and reasoning helpers** — public Memory Lab functionality is packaged in `memory_lab.*` modules.
- **Opt-in Postgres persistence** — `PostgresPersistenceBackend` is available only when explicitly configured; in-memory persistence remains the empty-env fallback.
- **Opt-in pgvector retrieval** — pgvector KNN retrieval and embedding storage are gated by migrations/configuration and do not replace deterministic fallback retrieval.
- **M11C raw retrieval parity surface** — `memory_lab_retrieval_search` / `/v1/retrieval/search` expose a public `search_raw_chunks` analogue with a structured retrieval envelope, normalized evidence metadata, per-result diagnostics (`retrieval_reason`, `ranking_reason`, `hub_match`, `graph_match`, `knowledge_path`, `score_components`, `distance`), and opt-in safe `debug_metadata.stage_metrics` for adapter search, normalize, deterministic retrieval, pgvector, hub inclusion, graph expansion, dedup/filtering, and degraded reasons. These diagnostics are descriptive observability, not ranking parity.
- **Opt-in provider-backed reasoning** — provider synthesis is disabled by default and requires explicit flags, request opt-in, and runtime provider keys.
- **Provider adapters** — OpenAI embeddings and Anthropic LLM adapters use deferred imports and degraded/no-key behavior.
- **Opt-in live smoke proof** — `scripts/m5_live_smoke.py` remains the opt-in live proof for real OpenAI embeddings, real Anthropic response, throwaway pgvector KNN rank #1, and grounded answer evidence when runtime-only secrets are supplied.

## What this is

- A public Memory Lab beta / release candidate for governed agent-memory experiments.
- A provider-neutral default runtime and helper library.
- A self-hosted package with optional DB/vector/provider paths.
- A public beta package and architecture reference for governed agent-memory experiments; PyPI publication and public announcement remain separate approvals.

## What this is not

- Not hosted production Context Brain.
- Not Full/private Context Brain parity.
- Not private `ask_v2` parity.
- Not full `query_memory` behavior parity with hosted/private Context Brain. OPENCB-M11C-1 added an opt-in, deployment-gated, provider-backed grounded-answer mode (declared `mode`, citation allow-list, typed degraded taxonomy) on top of the deterministic core. OPENCB-M11C-2 added a public raw retrieval envelope, result diagnostics, and opt-in safe stage metrics. This still does not replicate private provider-derived confidence scoring or full semantic/ranking parity.
- Intentional divergence (deferred decision): an unhandled server error surfaces as a standard HTTP 500, not a private-style typed 200 ask body with `status="error"`. FastAPI-native error semantics are preferred for a public API; the private `ask_v2` typed-unhandled-exception precedent was deliberately not copied in M11C-1.
- Not production tenancy, billing, monitoring, or operations.
- Not production MCP/GPT Actions deployment readiness.
- Not provider-backed semantic search or LLM reasoning by default.
- Not automatic truth arbitration, contradiction resolution, canonical-truth selection, or graph repair.
- Not permission to push, tag, publish to PyPI, or announce publicly.

## Runtime boundaries

- Baseline: no `OPENAI_API_KEY`, no `ANTHROPIC_API_KEY`, no `DATABASE_URL` required.
- Postgres: opt-in through explicit database configuration.
- pgvector: opt-in through explicit flags/migrations and vector-enabled DB.
- Providers: opt-in through explicit flags, request-level selection where applicable, installed extras/dependencies, and runtime-only keys.
- Semantic annotations: optional and best-effort; public storage/API should describe provider-neutral annotations, not vendor-specific tags.
- Save/ingest invariant: body persistence, dedup, deterministic classification, and governance must not require provider availability.
- Secrets: environment variable names may be documented; secret values, private `.env` files, and DSNs must not be committed or shipped in artifacts.
