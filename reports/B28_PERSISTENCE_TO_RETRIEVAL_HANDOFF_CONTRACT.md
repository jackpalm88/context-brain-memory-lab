# B28 Persistence-to-Retrieval Handoff Contract

## Status

- Milestone: B28 Persistence-to-Retrieval Handoff Contract
- Status: PASS_WITH_CAVEATS from post-push verification
- Public head: `d9132785bbf9d28c5b8c2bafab4b313c86be76d3`
- Parent: `51d6821b9ac9b513f71e078abb627191f0d7e898`
- Public version: `0.1.0b24`
- Completion classification: `public_safe_persistence_to_retrieval_handoff_contract_only_no_live_db_no_provider_no_private_cb_no_runtime_integration`

## Exact B28 Implementation Files

The B28 implementation commit changed exactly these five files:

- `memory_lab/retrieval/persistence_handoff.py`
- `tests/unit/test_b28_persistence_retrieval_context_package.py`
- `tests/unit/test_b28_persistence_retrieval_handoff.py`
- `tests/unit/test_b28_persistence_retrieval_public_safety.py`
- `tests/unit/test_b28_persistence_retrieval_workspace_boundary.py`

## Implemented Surface

Primary module:

- `memory_lab/retrieval/persistence_handoff.py`

Constants:

- `B28_HANDOFF_MODE`
- `B28_LIMITATIONS`
- `B28_NON_CLAIMS`

Objects:

- `PersistenceRetrievalCapabilityMetadata`
- `PersistenceRetrievalCandidateRequest`
- `PersistenceRetrievalCandidate`
- `PersistenceRetrievalHandoffResult`
- `PersistenceRetrievalHandoffError`
- `PublicSafePersistenceRetrievalHandoff`

Functions:

- `build_retrieval_candidates_from_records`
- `build_context_package_from_persisted_records`

## Behavior Proof

B28 establishes a public-safe, contract-only handoff from persistence-shaped records to B23-compatible retrieval/context inputs.

Confirmed behavior:

- Converts supplied `ContentPersistenceRecord` values into B23-compatible candidates.
- Converts mapping-shaped records that contain public-safe fields.
- Requires no backend for direct supplied records.
- Supports an optional supplied B26 backend through `list_content_records(workspace_id)`.
- Returns structured `backend_required` behavior when backend mode is requested without a backend.
- Returns structured `backend_result_failed` behavior when a supplied backend list operation fails.
- Preserves deterministic ordering by `item_id`.
- Produces bounded snippets.
- Provides structured `no_usable_records`, invalid-input, and workspace/boundary failures.
- Maintains read/list-only behavior for supplied backends.
- Does not mutate a supplied backend.
- Does not call `put_content_record` in the production module.

## Candidate Mapping Proof

Confirmed candidate mapping:

- `item_id` is derived from `content_id` when available, otherwise a safe fallback is used.
- Candidate text is derived from `text` or `content`.
- Snippets are bounded.
- `purpose_text` is derived from the title plus public-safe metadata signals.
- `domain` and `tags` are derived from metadata.
- `source_metadata` uses a public-safe allowlist only.
- `ingestion_score` is derived from `metadata.scoring_composite`.
- `tier` is derived from `metadata.tier_recommendation`.

## Context Package Proof

B28 connects to B23 rather than replacing it:

- Uses B23 `rank_context_candidates_by_purpose`.
- Uses B23 `build_context_candidates`.
- Remains supplied-record-only.
- Feeds B23-compatible supplied candidates and context package inputs.
- Does not replace B23 search-by-purpose or context candidate behavior.

## Boundary Proof

B28 implementation preserves the intended public-safe boundary:

- No live DB access.
- No `DATABASE_URL` or environment-variable access.
- No migrations, alembic, or schema changes.
- No provider calls.
- No private Context Brain access.
- No URL, HTTP, or network retrieval.
- No API, auth, or RBAC runtime implementation.
- No MCP or GPT Actions tools.
- No embeddings or vector retrieval behavior.
- No persistence, governance, ingestion, reasoning, or wrappers changes in the implementation commit.
- No README, docs, pyproject, or report changes in the implementation commit.
- No `memory_lab/retrieval/__init__.py` change.
- No `memory_lab/retrieval/init.py` creation.

## False Capability Metadata

B28 capability metadata remains explicitly false for runtime/integration claims:

- `live_backend_used = False`
- `requires_db = False`
- `requires_provider = False`
- `requires_private_context_brain = False`
- `uses_embeddings = False`
- `uses_vector_db = False`
- `mutates_external_state = False`

## Validation

Post-push verification results:

- `py_compile`: PASS
- B28 tests: `18 passed`
- B23 regression: `19 passed`
- B25 regression: `23 passed`
- B26 regression: `22 passed`
- B27 regression: `19 passed`
- Full unit suite: `726 passed, 9 skipped`
- Import smoke: `B28_IMPORT_SMOKE_PASS b28_public_safe_persistence_to_retrieval_handoff_v1 PublicSafePersistenceRetrievalHandoff`

## Safety Scans

- Runtime safety scan: `B28_RUNTIME_SAFETY_SCAN_PASS`
- Claim scan: `B28_CLAIM_SCAN_PASS`
- Allowed wording is limited to explicit limitations, explicit non-claims, or negative-test allowlists.

## Post-Push Verify Caveats

The post-push verify gate passed with non-blocking caveats:

- SSH clone failed with `Permission denied (publickey)`; public HTTPS fresh clone was used instead.
- Initial Windows CRLF checkout caused a deterministic fixture test failure; recloning with `core.autocrlf=false` resolved the issue and the full unit suite passed.
- An isolated temp venv was used for verification; the repo was not edited, committed, pushed, tagged, or built during post-push verification.

## Explicit Non-Claims

B28 explicitly does not claim:

- `not_live_memory_retrieval`
- `not_semantic_search`
- `not_db_backed_retrieval`
- `not_db_backed_production_persistence`
- `not_provider_backed_reasoning`
- `not_embedding_or_vector_retrieval`
- `not_private_context_brain_parity`
- `not_full_context_brain_parity`
- `not_api_or_mcp_runtime`
- `not_production_ready`

## Relationship to Prior Milestones

### Relationship to B23

- B28 feeds B23 with supplied candidates and context package inputs.
- B28 does not replace B23.

### Relationship to B25

- B28 enforces workspace validation and workspace boundary behavior.

### Relationship to B26

- B28 may read/list records from a supplied B26 backend only.
- B28 does not add DB adapters.
- B28 does not add migrations.

### Relationship to B27

- B27 can persist to a supplied B26 backend.
- B28 transforms those persisted records into retrieval/context candidates.

## Recommended Next Milestone

Recommended next milestone:

- B28 milestone report push precheck and push for the persistence-to-retrieval handoff contract report

Recommended next gate:

- `GO_B28_MILESTONE_REPORT_PUSH_PRECHECK_AND_PUSH_PERSISTENCE_TO_RETRIEVAL_HANDOFF_CONTRACT`
