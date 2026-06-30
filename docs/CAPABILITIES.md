# Public capabilities and boundaries

Current package version: `0.2.0a1`.

This document is the compact truth map for the public Memory Lab beta after M10.3. It supersedes older B-era and M1–M5 wording as the current capability/boundary reference while preserving the same public-safety boundaries.

## Implemented and proven

- **Deterministic empty-env core** — imports, deterministic helpers, and hermetic tests run without provider keys, without private Context Brain access, and without a configured database.
- **Workspace-aware API and retrieval surfaces** — FastAPI routers and evidence contracts remain public-beta and self-hosted.
- **MCP parity surface** — 32/32 approved Context Brain-compatible MCP tool names are registered in the public Memory Lab MCP surface.
- **Content body persistence** — created content bodies are persisted to `content_chunks` through a shared body persistence primitive.
- **Workspace-scoped content dedup** — content creation computes `content_hash` and uses a workspace-scoped unique index/friendly duplicate response when Postgres persistence is configured.
- **Deterministic classification and current-state substrate** — public classification/current-state logic remains provider-free and does not claim semantic truth understanding.
- **Optional semantic annotations** — `topic_tags` and `meta_tags` can be produced as provider-neutral, best-effort enrichment; save/ingest success does not depend on provider availability.
- **Canonical query/evidence seams + opt-in grounded answer** — public query paths normalize evidence, project `AskResponse` through canonical seams, declare a `mode` (`deterministic|provider_backed|degraded`), and accept an optional `memory_type` filter. When explicitly opted in per request and enabled by deployment config, the answer is provider-backed wording bounded to retrieved evidence, enforced by a citation allow-list (no invented citations) and a typed degraded fallback. This is bounded evidence-grounded wording, not private `ask_v2` ranking/confidence/debug parity.
- **Decision, graph, governance, context-pack, and reasoning helpers** — public Memory Lab functionality is packaged in `memory_lab.*` modules.
- **Opt-in Postgres persistence** — `PostgresPersistenceBackend` is available only when explicitly configured; in-memory persistence remains the empty-env fallback.
- **Opt-in pgvector retrieval** — pgvector KNN retrieval and embedding storage are gated by migrations/configuration and do not replace deterministic fallback retrieval.
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
- Not full `query_memory` behavior parity with hosted/private Context Brain. OPENCB-M11C-1 added an opt-in, deployment-gated, provider-backed grounded-answer mode (declared `mode`, citation allow-list, typed degraded taxonomy) on top of the deterministic core — but it does not replicate private provider-derived confidence scoring, full semantic ranking, or `search_raw_chunks` debug diagnostics.
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
