# B16 Public Repo Application Review

Gate: `GO_B16_PUBLIC_REPO_APPLICATION_REVIEW`  
Status: `B16_PUBLIC_REPO_APPLICATION_REVIEW_PASS_WITH_CAVEATS`  
Generated UTC: `2026-06-14T18:22:17Z`

## Baseline

- public repo: `https://github.com/jackpalm88/context-brain-memory-lab.git`
- expected B15 baseline: `2a131135e86ea933b63789bf19b7ced13618a0c3`
- verified HEAD: `2a131135e86ea933b63789bf19b7ced13618a0c3`
- origin URL: `https://github.com/jackpalm88/context-brain-memory-lab.git`

Baseline check: PASS.

## Applied B16 candidate files

Tracked modified files:
- `memory_lab/api/routers/graph_health.py`
- `memory_lab/graph/health_models.py`
- `memory_lab/graph/health_service.py`
- `memory_lab/reports/graph_health_report.py`
- `tests/integration/test_graph_health_api.py`

New untracked candidate files:
- `memory_lab/api/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/api/__pycache__/auth_context.cpython-312.pyc`
- `memory_lab/api/__pycache__/config.cpython-312.pyc`
- `memory_lab/api/__pycache__/main.cpython-312.pyc`
- `memory_lab/api/__pycache__/workspace_context.cpython-312.pyc`
- `memory_lab/api/dependencies/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/api/dependencies/__pycache__/auth.cpython-312.pyc`
- `memory_lab/api/policies/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/api/policies/__pycache__/content_quality.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/ask.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/cleanup.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/conflicts.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/content.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/context_packs.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/decisions.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/edges.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/graph_health.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/health.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/hubs.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/reasoning.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/retrieval.cpython-312.pyc`
- `memory_lab/api/routers/__pycache__/tier_override.cpython-312.pyc`
- `memory_lab/api/services/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/api/services/__pycache__/api_adapter.cpython-312.pyc`
- `memory_lab/api/services/__pycache__/content_quality.cpython-312.pyc`
- `memory_lab/api/services/__pycache__/retrieval_adapter.cpython-312.pyc`
- `memory_lab/api/utils/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/api/utils/__pycache__/content_signatures.cpython-312.pyc`
- `memory_lab/bootstrap/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/bootstrap/__pycache__/config.cpython-312.pyc`
- `memory_lab/bootstrap/__pycache__/smoke.cpython-312.pyc`
- `memory_lab/bootstrap/__pycache__/stores.cpython-312.pyc`
- `memory_lab/conflicts/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/conflicts/__pycache__/detector.cpython-312.pyc`
- `memory_lab/conflicts/__pycache__/markers.cpython-312.pyc`
- `memory_lab/conflicts/__pycache__/models.cpython-312.pyc`
- `memory_lab/conflicts/__pycache__/service.cpython-312.pyc`
- `memory_lab/context_packs/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/context_packs/__pycache__/builder.cpython-312.pyc`
- `memory_lab/context_packs/__pycache__/models.cpython-312.pyc`
- `memory_lab/context_packs/__pycache__/service.cpython-312.pyc`
- `memory_lab/current_state/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/current_state/__pycache__/resolver.cpython-312.pyc`
- `memory_lab/decisions/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/decisions/__pycache__/models.cpython-312.pyc`
- `memory_lab/decisions/__pycache__/store.cpython-312.pyc`
- `memory_lab/governance/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/governance/__pycache__/events.cpython-312.pyc`
- `memory_lab/governance/__pycache__/ingestion_policy.cpython-312.pyc`
- `memory_lab/governance/__pycache__/tier_router.cpython-312.pyc`
- `memory_lab/governance/__pycache__/transition_matrix.cpython-312.pyc`
- `memory_lab/graph/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/graph/__pycache__/adapter.cpython-312.pyc`
- `memory_lab/graph/__pycache__/alias_hygiene.cpython-312.pyc`
- `memory_lab/graph/__pycache__/alias_store.cpython-312.pyc`
- `memory_lab/graph/__pycache__/edge.cpython-312.pyc`
- `memory_lab/graph/__pycache__/expansion.cpython-312.pyc`
- `memory_lab/graph/__pycache__/health_models.cpython-312.pyc`
- `memory_lab/graph/__pycache__/health_service.cpython-312.pyc`
- `memory_lab/graph/__pycache__/hub_edge_store.cpython-312.pyc`
- `memory_lab/graph/__pycache__/hub_recall_health.cpython-312.pyc`
- `memory_lab/graph/__pycache__/hub_store.cpython-312.pyc`
- `memory_lab/graph/__pycache__/hybrid_search.cpython-312.pyc`
- `memory_lab/graph/__pycache__/repository_reader.cpython-312.pyc`
- `memory_lab/graph/__pycache__/store.cpython-312.pyc`
- `memory_lab/graph/repository_reader.py`
- `memory_lab/ingestion/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/ingestion/__pycache__/chunk_scorer_v2.cpython-312.pyc`
- `memory_lab/ingestion/__pycache__/classify_catchup.cpython-312.pyc`
- `memory_lab/ingestion/__pycache__/classify_pipeline.cpython-312.pyc`
- `memory_lab/ingestion/__pycache__/models.cpython-312.pyc`
- `memory_lab/ingestion/__pycache__/scorer.cpython-312.pyc`
- `memory_lab/mcp/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/mcp/__pycache__/client.cpython-312.pyc`
- `memory_lab/mcp/__pycache__/server.cpython-312.pyc`
- `memory_lab/mcp/__pycache__/tools.cpython-312.pyc`
- `memory_lab/providers/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/providers/__pycache__/anthropic.cpython-312.pyc`
- `memory_lab/providers/__pycache__/config.cpython-312.pyc`
- `memory_lab/providers/__pycache__/embedding_backend.cpython-312.pyc`
- `memory_lab/providers/__pycache__/failure.cpython-312.pyc`
- `memory_lab/providers/__pycache__/fake.cpython-312.pyc`
- `memory_lab/providers/__pycache__/llm_backend.cpython-312.pyc`
- `memory_lab/providers/__pycache__/noop.cpython-312.pyc`
- `memory_lab/providers/__pycache__/openai_embedding.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/answer.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/answer_synthesizer.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/explain.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/intent_detector.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/models.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/policy_generator.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/service.cpython-312.pyc`
- `memory_lab/reasoning/__pycache__/traverse.cpython-312.pyc`
- `memory_lab/reports/__pycache__/__init__.cpython-312.pyc`
- `memory_lab/reports/__pycache__/graph_health_report.cpython-312.pyc`
- `scripts/__pycache__/b15_graph_health_report.cpython-312.pyc`
- `tests/__pycache__/__init__.cpython-312.pyc`
- `tests/__pycache__/conftest.cpython-312-pytest-7.4.4.pyc`
- `tests/__pycache__/conftest.cpython-312.pyc`
- `tests/integration/__pycache__/__init__.cpython-312.pyc`
- `tests/integration/__pycache__/test_classify_ingest_wiring_integration.cpython-312.pyc`
- `tests/integration/__pycache__/test_conflicts_api.cpython-312.pyc`
- `tests/integration/__pycache__/test_context_pack_api.cpython-312.pyc`
- `tests/integration/__pycache__/test_graph_health_api.cpython-312-pytest-7.4.4.pyc`
- `tests/integration/__pycache__/test_graph_health_api.cpython-312.pyc`
- `tests/integration/__pycache__/test_graph_layer.cpython-312.pyc`
- `tests/integration/__pycache__/test_hub_edges.cpython-312.pyc`
- `tests/integration/__pycache__/test_reasoning_answer_api.cpython-312.pyc`
- `tests/integration/__pycache__/test_reasoning_api.cpython-312.pyc`
- `tests/smoke/__pycache__/__init__.cpython-312.pyc`
- `tests/smoke/__pycache__/test_b15_graph_health_report.cpython-312-pytest-7.4.4.pyc`
- `tests/smoke/__pycache__/test_b15_graph_health_report.cpython-312.pyc`
- `tests/smoke/__pycache__/test_package_assets.cpython-312.pyc`
- `tests/unit/__pycache__/__init__.cpython-312.pyc`
- `tests/unit/__pycache__/test_alias_hygiene_candidates.cpython-312-pytest-7.4.4.pyc`
- `tests/unit/__pycache__/test_alias_hygiene_candidates.cpython-312.pyc`
- `tests/unit/__pycache__/test_chunk_scorer_v2.cpython-312.pyc`
- `tests/unit/__pycache__/test_classify_catchup.cpython-312.pyc`
- `tests/unit/__pycache__/test_classify_ingest_wiring.cpython-312.pyc`
- `tests/unit/__pycache__/test_conflict_detector.cpython-312.pyc`
- `tests/unit/__pycache__/test_conflict_markers.cpython-312.pyc`
- `tests/unit/__pycache__/test_context_pack_builder.cpython-312.pyc`
- `tests/unit/__pycache__/test_current_state_resolver.cpython-312.pyc`
- `tests/unit/__pycache__/test_governance_events.cpython-312.pyc`
- `tests/unit/__pycache__/test_governance_lines.cpython-312.pyc`
- `tests/unit/__pycache__/test_graph_health_report_repository_mode.cpython-312-pytest-7.4.4.pyc`
- `tests/unit/__pycache__/test_graph_health_report_repository_mode.cpython-312.pyc`
- `tests/unit/__pycache__/test_graph_health_repository_integration.cpython-312-pytest-7.4.4.pyc`
- `tests/unit/__pycache__/test_graph_health_repository_integration.cpython-312.pyc`
- `tests/unit/__pycache__/test_graph_health_service.cpython-312-pytest-7.4.4.pyc`
- `tests/unit/__pycache__/test_graph_health_service.cpython-312.pyc`
- `tests/unit/__pycache__/test_hub_recall_health.cpython-312-pytest-7.4.4.pyc`
- `tests/unit/__pycache__/test_hub_recall_health.cpython-312.pyc`
- `tests/unit/__pycache__/test_ingestion_policy.cpython-312.pyc`
- `tests/unit/__pycache__/test_ingestion_scorer.cpython-312.pyc`
- `tests/unit/__pycache__/test_reasoning_answer.cpython-312.pyc`
- `tests/unit/__pycache__/test_reasoning_explain.cpython-312.pyc`
- `tests/unit/__pycache__/test_reasoning_traverse.cpython-312.pyc`
- `tests/unit/__pycache__/test_repository_graph_health_reader.cpython-312-pytest-7.4.4.pyc`
- `tests/unit/__pycache__/test_repository_graph_health_reader.cpython-312.pyc`
- `tests/unit/__pycache__/test_retrieval_evidence_contract.cpython-312.pyc`
- `tests/unit/__pycache__/test_retrieval_memory_type_filter.cpython-312.pyc`
- `tests/unit/__pycache__/test_tier_router.cpython-312.pyc`
- `tests/unit/ingestion/__pycache__/__init__.cpython-312.pyc`
- `tests/unit/ingestion/__pycache__/test_classify_pipeline.cpython-312.pyc`
- `tests/unit/ingestion/__pycache__/test_scorer_provider_backend.cpython-312.pyc`
- `tests/unit/providers/__pycache__/__init__.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_anthropic_adapter.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_embedding_backend_contract.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_failure_codes.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_fake_backend.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_noop_backend.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_openai_embedding_adapter.cpython-312.pyc`
- `tests/unit/providers/__pycache__/test_schema_validation.cpython-312.pyc`
- `tests/unit/test_graph_health_report_repository_mode.py`
- `tests/unit/test_graph_health_repository_integration.py`
- `tests/unit/test_repository_graph_health_reader.py`

No staging B16 reports were copied. Only these sanitized review reports were generated in `reports/`.

## Protected files

Protected files/directories remain unchanged:

- `pyproject.toml` — unchanged, version remains `0.1.0b15`
- `README.md` / `docs/` — unchanged
- `migrations/` — unchanged
- `memory_lab/api/main.py` — unchanged
- `dist/` — unchanged / not used for release publication

## Validation

PASS:

- remote HEAD baseline verification
- clean worktree before B16 application
- protected diff check
- unsanitized staging report copy check
- `python3 -m compileall -q memory_lab tests`
- targeted B16+B15 tests: `75 passed in 5.01s`
- route smoke for all three B16 endpoints
- B16 candidate forbidden scan
- public source/tests private value/path scan

## Diff summary

- 5 tracked files changed before report generation
- 4 new B16 candidate files before report generation
- diff stat: 743 insertions, 45 deletions in tracked files

## Non-claims

- No production repository-backed live graph claim.
- No live DB/private CB access claim.
- No ingestion intelligence claim.
- No embeddings operations claim.
- No graph mutation or repair claim.
- No alias auto-merge claim.
- No Full Context Brain claim.
- No public push/release/PyPI claim.
- No CB milestone save claim.
- No scorecard update claim.

## Caveats

- pyproject.toml remains 0.1.0b15; version/release gate is still required before any publishable B16 artifact.
- Application review changes are present only in a local public-repo worktree and have not been pushed.
- Generated reports are sanitized review evidence; prior staging reports were not copied because they may contain local staging path references.
- No production repository/session provider is wired; repository mode still reports explicit unavailable without provider injection.

## Next gate

Recommended next gate: `GO_B16_PUBLIC_PUSH_PRECHECK`.

No public push, GitHub release, PyPI, CB milestone save, or scorecard update was performed.
