# Public capabilities and boundaries

This document summarizes the public-safe capability spine for Context Brain Memory Lab after the B18-B31 implementation gates. It is a documentation alignment aid; it does not change the package version, runtime behavior, or release status.

Current public package version: `0.1.0b24`.

## What is implemented

- **B18 extraction/domain signals** — deterministic extraction/domain helpers for caller-supplied content and fixtures.
- **B19 hub/tag signals** — bounded hub/tag signal helpers over supplied evidence.
- **B20 embedding admin planning + deterministic KNN core** — planning contracts and deterministic nearest-neighbor logic over supplied vectors; no vector DB is required by default.
- **B21 scoring/tier/circuit** — deterministic evaluation of supplied ingestion signals, tier-routing plans, and circuit state.
- **B22 LLM executor contract + structured validator** — public-safe executor contracts and validation for caller-supplied structured outputs, including degraded/no-provider behavior.
- **B23 search/context/prompt package helpers** — deterministic supplied-input candidate ranking and prompt-package assembly.
- **B24 bounded honest wrapper contracts** — selected MCP/GPT Actions-style wrapper descriptors, schemas, examples, and tools for supplied-input workflows.
- **B25 governance state model + workspace boundary contract** — public-safe governance state and workspace-boundary primitives for supplied records/events only.
- **B26 in-memory persistence backend contract** — deterministic persistence interfaces and in-memory backend behavior; no DB-backed production persistence.
- **B27 public-safe ingestion pipeline contract** — deterministic supplied-text ingestion orchestration over caller-supplied input, optional supplied B26 backend only.
- **B28 persistence-to-retrieval handoff contract** — transforms supplied persistence-shaped records into B23-compatible retrieval/context candidates without live DB, provider, or vector retrieval.
- **B29 persisted-record-to-prompt-package handoff contract** — builds prompt packages and B22-compatible request shapes from supplied persisted-record-shaped inputs without executing an LLM.
- **B30 supplied-text-to-prompt-request flow contract** — shapes caller-supplied text into prompt-package / prompt-request structures without provider execution.
- **B31 bounded wrapper exposure for supplied-text prompt flow** — static bounded wrapper descriptors and tools for `build_supplied_text_prompt_package` and `build_supplied_text_prompt_request_shape`.

## What this is

- A public Memory Lab beta for governed agent-memory experiments.
- A provider-neutral default runtime and helper library.
- A set of deterministic/public-safe contracts for supplied input, local fixtures, and explicit API paths.
- A foundation for later governance, release, and production-transition work.

## What this is not

- Not production-ready hosted Context Brain.
- Not Full/private Context Brain parity.
- Not private `ask_v2` parity.
- Not live memory retrieval by default.
- Not provider-backed semantic search by default.
- Not production MCP readiness.
- Not production GPT Actions readiness.
- No runtime API/MCP/GPT Actions deployment.
- No production readiness.
- No live LLM execution or provider-backed answer generation.
- No DB/private Context Brain access.
- No embeddings/vector DB execution.
- No release/tag/PyPI/build/export completion.
- Not a vector database or embedding provider requirement.
- Not automatic truth arbitration, contradiction resolution, or graph repair.

## Wrapper boundary

B24/B31 wrappers are bounded honest adapters over supplied input. Their descriptors and examples are static contracts. B31 adds static wrapper exposure for the B30 supplied-text prompt flow through `build_supplied_text_prompt_package` and `build_supplied_text_prompt_request_shape`. They do not claim a deployed server URL, auth flow, live backend, DB-backed retrieval, private Context Brain access, embeddings generation, vector search, provider-backed reasoning, LLM execution, state mutation, API/MCP/GPT Actions runtime deployment, or production integration readiness.

## Next direction

- Repo and release hygiene.
- Keep public docs, package metadata, and proof evidence aligned after B25-B31 before any release/tag/PyPI step.
- Future production transition work only after separate proof gates.
