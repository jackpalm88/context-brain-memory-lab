# Public capabilities and boundaries

This document summarizes the public-safe capability spine for Context Brain Memory Lab after the B18-B24 implementation gates. It is a documentation alignment aid; it does not change the package version, runtime behavior, or release status.

Current public package version: `0.1.0b17`.

## What is implemented

- **B18 extraction/domain signals** — deterministic extraction/domain helpers for caller-supplied content and fixtures.
- **B19 hub/tag signals** — bounded hub/tag signal helpers over supplied evidence.
- **B20 embedding admin planning + deterministic KNN core** — planning contracts and deterministic nearest-neighbor logic over supplied vectors; no vector DB is required by default.
- **B21 scoring/tier/circuit** — deterministic evaluation of supplied ingestion signals, tier-routing plans, and circuit state.
- **B22 LLM executor contract + structured validator** — public-safe executor contracts and validation for caller-supplied structured outputs, including degraded/no-provider behavior.
- **B23 search/context/prompt package helpers** — deterministic supplied-input candidate ranking and prompt-package assembly.
- **B24 bounded honest wrapper contracts** — selected MCP/GPT Actions-style wrapper descriptors, schemas, examples, and tools for supplied-input workflows.

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
- Not a vector database or embedding provider requirement.
- Not automatic truth arbitration, contradiction resolution, or graph repair.

## Wrapper boundary

B24 wrappers are bounded honest adapters over supplied input. Their descriptors and examples are static contracts. They do not claim a deployed server URL, auth flow, live backend, DB-backed retrieval, private Context Brain access, embeddings generation, vector search, provider-backed reasoning, state mutation, or production integration readiness.

## Next direction

- Repo and release hygiene.
- B25 governance state model and workspace boundary.
- Future production transition work only after separate proof gates.
