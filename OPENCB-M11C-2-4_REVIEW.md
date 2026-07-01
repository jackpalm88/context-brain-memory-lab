# OPENCB-M11C-2-4_REVIEW.md — MCP Polish and Documentation

Status: local review deliverable for acceptance. No push until accepted.

## Scope guard

M11C-2-4 is documentation and implementation-polish only. This review explicitly avoids:

- retrieval behavior changes
- ranking changes
- diagnostics changes
- `stage_metrics` changes
- provider changes
- graph expansion changes

## Findings

1. MCP surface
   - `memory_lab_retrieval_search` already exposed the M11C-2 raw retrieval path, but its Python function had no docstring for FastMCP/tool readers.
   - The MCP wrapper forwards `query`, `limit`, `debug`, `only_clean`, and `workspace_id`.
   - API-level `memory_type`/`memory_types` filters exist on `/v1/retrieval/search`, but adding them to the MCP wrapper would be a tool-shape and behavior change, so M11C-2-4 documents this honestly instead of adding parameters.

2. API and OpenAPI surface
   - `/v1/retrieval/search` had the correct request/response behavior, but request fields lacked explicit OpenAPI descriptions.
   - `debug=false` and `debug=true` behavior needed plain-language documentation in schema/docs.
   - `only_clean` needed honest wording: public M11C-2 accepts and reports it as compatibility metadata, not a private clean/dirty retrieval filter.

3. Capability documentation
   - `docs/CAPABILITIES.md` still reflected post-M10.3 wording and said `search_raw_chunks` debug diagnostics were not present. That became stale after M11C-2-1, M11C-2-2, and M11C-2-3.
   - `MCP_PARITY_TABLE.md` still had a stale final boundary sentence saying `search_raw_chunks` debug diagnostics remained private/provider territory.

## Tiny fixes performed

- Added a docstring to `memory_lab_retrieval_search` describing:
  - public `search_raw_chunks` analogue
  - `query`, `limit`, `debug`, `only_clean`, and `workspace_id`
  - `debug=true` safe stage metrics
  - `debug=false` clean response
  - `only_clean` accepted-noop compatibility semantics
  - API-level `memory_type`/`memory_types` filters not forwarded by MCP in this docs-only slice
- Added OpenAPI `Field` descriptions and examples to `RetrievalRequest`.
- Added endpoint summary/docstring for `/v1/retrieval/search`.
- Updated `docs/CAPABILITIES.md` to describe M11C raw retrieval envelope, result diagnostics, and stage metrics while preserving the boundary that M12 ranking parity is not done.
- Updated `MCP_PARITY_TABLE.md` with an M11C-2 raw retrieval MCP polish status section.
- Added documentation/schema contract tests for the MCP docstring and OpenAPI schema wording.

## Acceptance notes

- The implementation remains diagnostics/documentation-only.
- No retrieval adapter logic was changed.
- No ranking/scoring/provider/stage_metrics logic was changed.
- No MCP parameters were added.
- M12 ranking parity remains unopened.
