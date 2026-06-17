# B27 Public-Safe Ingestion Pipeline Contract

## Milestone identity

- Milestone name: B27 Public-Safe Ingestion Pipeline Contract
- Roadmap label: B27 Live Ingestion Pipeline
- Status: PASS, public-safe contract/orchestration only
- Public head: `523e44fe7576b67f6182eff0e737dbb630fcb259`
- Parent: `757dc565a0a5a369af0311411de74d4496d015a8`
- Public version: `0.1.0b24`
- Completion classification: `public_safe_ingestion_pipeline_contract_only_no_live_db_no_provider_no_private_cb_no_runtime_integration`

B27 satisfies the roadmap gap by adding a bounded, deterministic ingestion pipeline contract. It does not add a production ingestion runtime, DB-backed production persistence, private Context Brain access, live retrieval, provider-backed reasoning, or MCP/GPT Actions production readiness.

## Exact B27 implementation commit files

The public implementation commit contains exactly these B27 files:

- `memory_lab/ingestion/pipeline_contract.py`
- `tests/unit/test_b27_ingestion_pipeline_contract.py`
- `tests/unit/test_b27_ingestion_pipeline_persistence_boundary.py`
- `tests/unit/test_b27_ingestion_pipeline_public_safety.py`
- `tests/unit/test_b27_ingestion_pipeline_workspace_boundary.py`

## Implemented surface

- `memory_lab/ingestion/pipeline_contract.py`
- `B27_PIPELINE_MODE`
- `B27_LIMITATIONS`
- `B27_NON_CLAIMS`
- `IngestionPipelineRequest`
- `IngestionPipelineResult`
- `IngestionPipelineError`
- `PublicSafeIngestionPipeline`
- `run_ingestion_pipeline`
- `make_public_safe_ingestion_pipeline`

## Typo proof

- `IngestionPipelineResult`: present in actual code and import smoke
- `InestionPipelineResult`: absent from actual code

## Behavior proof

B27 behavior is limited to deterministic, public-safe orchestration over caller-supplied inputs:

- caller-supplied input only
- `workspace_id` is required and B25-validated
- `content_id` is required
- `text` is required and non-blank
- `source_ref` is metadata-only and not fetched
- deterministic B18 extraction/domain signal is used
- deterministic B19 hub/tag signal is used
- B21 chunk scoring, ingestion scoring, circuit evaluation, and tier planning are used
- B25 workspace validation is used
- optional B26 supplied persistence backend only
- `persist=false` requires no backend and does not mutate persistence
- `persist=true` without backend returns structured `persistence_backend_required`
- `persist=true` with `InMemoryPersistenceBackend` writes through B26 `put_content_record` only
- no DB fallback exists
- workspace boundary is preserved
- repeated writes remain idempotent through B26 backend behavior

## Boundary proof

B27 intentionally excludes runtime, private, provider, and production behaviors:

- no DB access
- no `DATABASE_URL`
- no migrations
- no provider calls
- no private Context Brain access
- no URL fetch or HTTP content retrieval
- no API/auth/RBAC runtime
- no MCP/GPT Actions tools
- no embeddings/vector retrieval behavior
- no retrieval/context pack/wrapper changes
- no `pyproject.toml` version change in the implementation commit
- no README/docs/report changes in the implementation commit
- no production ingestion runtime

## Validation proof

- `python3 -m py_compile memory_lab/ingestion/pipeline_contract.py`: PASS
- B27 tests: `19 passed`
- B18/B19/B21/B25/B26 regressions: `114 passed`
- Full unit suite: `708 passed, 9 skipped`
- Import smoke: `B27_IMPORT_SMOKE_PASS b27_public_safe_ingestion_pipeline_contract_v1 IngestionPipelineResult`

## Safety proof

- Runtime safety scan: PASS
- Claim scan: PASS
- Allowed hits only in explicit limitations/non-claims or negative-test allowlists

## Explicit non-claims

- `not_production_ingestion_runtime`
- `not_db_backed_production_persistence`
- `not_live_context_brain_ingestion`
- `not_private_context_brain_parity`
- `not_live_memory_retrieval`
- `not_semantic_search`
- `not_provider_backed_reasoning`
- `not_mcp_or_gpt_actions_production_ready`

## Relationship to prior milestones

- B18 supplies deterministic extraction/domain pieces.
- B19 supplies deterministic hub/tag signal pieces.
- B21 supplies scoring/circuit/tier plan primitives.
- B25 supplies workspace validation and governance boundary.
- B26 supplies optional backend interface and in-memory test backend.

## Recommended next milestone

Recommended next milestone: B28 gap contract for bounded retrieval/persistence integration or the next agreed roadmap gap.

Recommended next gate for this report: `GO_B27_MILESTONE_REPORT_REVIEW_AND_COMMIT_LIVE_INGESTION_PIPELINE`.
