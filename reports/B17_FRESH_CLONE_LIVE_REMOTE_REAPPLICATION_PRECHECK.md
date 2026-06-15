# B17 Fresh Clone Live Remote Reapplication Precheck

Gate: `GO_B17_FRESH_CLONE_LIVE_REMOTE_REAPPLICATION_PRECHECK`

Status: `B17_FRESH_CLONE_LIVE_REMOTE_REAPPLICATION_PRECHECK_PASS_WITH_CAVEATS`

Timestamp UTC: `2026-06-15T04:37:22Z`

Mode: fresh baseline precheck only. No B17 file application, source/test/config/docs changes, commit, push, merge, rebase, reset, cherry-pick, CB write, or scorecard update was performed.

## 1. Fresh clone/worktree identity

- fresh path selected: `/opt/context-brain-memory-lab_b17_fresh_live_remote`
- remote URL: `git@github.com:jackpalm88/context-brain-memory-lab.git`
- branch: `main`
- HEAD: `f5f1db4ae74217ce93b96eac8ff948481030d0e9`
- HEAD equals authoritative live remote HEAD: `True`
- clean worktree status before report outputs: `True`
- tracked diff files before reports: `0`
- staged files before reports: `0`
- untracked files before reports: `0`
- pycache count: `0`

## 2. Live remote baseline

- live remote refs/heads/main: `f5f1db4ae74217ce93b96eac8ff948481030d0e9`
- expected authoritative HEAD: `f5f1db4ae74217ce93b96eac8ff948481030d0e9`
- live remote matches expected: `True`
- fresh local HEAD equals live remote HEAD: `True`
- origin/main...HEAD ahead/behind: `0	0`
- no divergence: `True`
- no stale origin/main state: `True`

## 3. B17 path conflict precheck

- approved B17 path count: `16`
- existing B17 paths on fresh live base: `0`

- checked: `tests/fixtures/b17_ingestion/synthetic_ingestion_fixtures.json`
- checked: `tests/unit/test_b17_synthetic_ingestion_fixtures.py`
- checked: `memory_lab/ingestion/interfaces.py`
- checked: `tests/unit/test_b17_ingestion_interface_scaffold.py`
- checked: `memory_lab/ingestion/chunking.py`
- checked: `tests/unit/test_b17_deterministic_content_chunker.py`
- checked: `memory_lab/ingestion/chunk_scoring.py`
- checked: `tests/unit/test_b17_deterministic_chunk_scorer.py`
- checked: `memory_lab/ingestion/embedding_health.py`
- checked: `tests/unit/test_b17_embedding_ops_read_only_health.py`
- checked: `memory_lab/ingestion/classifiers.py`
- checked: `tests/unit/test_b17_classifier_noop.py`
- checked: `memory_lab/ingestion/extraction.py`
- checked: `tests/unit/test_b17_content_extraction_noop.py`
- checked: `memory_lab/ingestion/embedding_health_adapter.py`
- checked: `tests/unit/test_b17_repository_embedding_health_adapter.py`

No exact B17 paths are present on the fresh live base.

## 4. Package/import compatibility precheck

- memory_lab_ingestion_dir_exists: `True`
- memory_lab_ingestion_init_exists: `True`
- tests_unit_dir_exists: `True`
- pyproject_exists: `True`
- package_metadata_version_change_needed: `False`
- pyproject_has_setuptools_or_project_config: `True`
- compatible_for_future_b17_package_application: `True`

## 5. Protected no-change precheck

Future B17 application must not touch:
- README.md
- pyproject.toml
- package version metadata
- API routers/main
- migrations
- docs
- config/env files
- build/release files
- scorecard reports

No pyproject/version/API change appears necessary for the future source/test package application.

## 6. Source package reference

- preferred source path: `/opt/context-brain-memory-lab_pr1a_staging`
- source policy: reviewed staging/audit source files; not stale commit cherry-pick
- all 16 approved files available: `True`
- available count: `16`
- missing files: `0`
- hashes can be compared to stale reference: `True`
- all source hashes match stale reference: `True`


## 7. Report artifact policy confirmation

- Apply only the 16 B17 source/test/fixture files first.
- Regenerate fresh live-base reports.
- Do not carry stale public-application reports into the new commit by default.

## 8. Public-safe precheck

- candidate operational source hits: `0`
- candidate test/fixture hits: `61`
- fresh base high-signal private hits: `3`
- scan ok: `True`

Test/fixture defensive/synthetic hits:
- `{'file': 'tests/unit/test_b17_synthetic_ingestion_fixtures.py', 'kind': 'provider', 'match': 'openai', 'line': 31}`
- `{'file': 'tests/unit/test_b17_synthetic_ingestion_fixtures.py', 'kind': 'provider', 'match': 'anthropic', 'line': 32}`
- `{'file': 'tests/unit/test_b17_synthetic_ingestion_fixtures.py', 'kind': 'provider', 'match': 'anthropic', 'line': 142}`
- `{'file': 'tests/unit/test_b17_synthetic_ingestion_fixtures.py', 'kind': 'provider', 'match': 'openai', 'line': 142}`
- `{'file': 'tests/unit/test_b17_synthetic_ingestion_fixtures.py', 'kind': 'db', 'match': 'postgres', 'line': 149}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'provider', 'match': 'anthropic', 'line': 161}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'provider', 'match': 'openai', 'line': 161}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'provider', 'match': 'anthropic', 'line': 162}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'provider', 'match': 'openai', 'line': 162}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'provider', 'match': 'openai', 'line': 175}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'provider', 'match': 'anthropic', 'line': 176}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'db', 'match': 'psycopg2', 'line': 161}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 161}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'db', 'match': 'psycopg2', 'line': 162}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 162}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'db', 'match': 'postgres', 'line': 179}`
- `{'file': 'tests/unit/test_b17_ingestion_interface_scaffold.py', 'kind': 'private_prompt_or_ip', 'match': 'conting.superagents.solutions', 'line': 174}`
- `{'file': 'tests/unit/test_b17_deterministic_content_chunker.py', 'kind': 'provider', 'match': 'openai', 'line': 166}`
- `{'file': 'tests/unit/test_b17_deterministic_content_chunker.py', 'kind': 'provider', 'match': 'anthropic', 'line': 167}`
- `{'file': 'tests/unit/test_b17_deterministic_content_chunker.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 168}`
- `{'file': 'tests/unit/test_b17_deterministic_content_chunker.py', 'kind': 'private_prompt_or_ip', 'match': '/opt/contentingestor', 'line': 178}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'provider', 'match': 'anthropic', 'line': 208}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'provider', 'match': 'openai', 'line': 208}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'provider', 'match': 'anthropic', 'line': 209}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'provider', 'match': 'openai', 'line': 209}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'db', 'match': 'psycopg2', 'line': 220}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 220}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'db', 'match': 'psycopg2', 'line': 221}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 221}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'db', 'match': 'postgres', 'line': 227}`
- `{'file': 'tests/unit/test_b17_deterministic_chunk_scorer.py', 'kind': 'private_prompt_or_ip', 'match': 'conting.superagents.solutions', 'line': 227}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'provider', 'match': 'anthropic', 'line': 249}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'provider', 'match': 'openai', 'line': 249}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'provider', 'match': 'anthropic', 'line': 250}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'provider', 'match': 'openai', 'line': 250}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'provider', 'match': 'openai', 'line': 275}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'provider', 'match': 'anthropic', 'line': 276}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'db', 'match': 'psycopg2', 'line': 249}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 249}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'db', 'match': 'psycopg2', 'line': 250}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 250}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'db', 'match': 'postgres', 'line': 279}`
- `{'file': 'tests/unit/test_b17_embedding_ops_read_only_health.py', 'kind': 'private_prompt_or_ip', 'match': 'conting.superagents.solutions', 'line': 274}`
- `{'file': 'tests/unit/test_b17_classifier_noop.py', 'kind': 'provider', 'match': 'anthropic', 'line': 19}`
- `{'file': 'tests/unit/test_b17_classifier_noop.py', 'kind': 'provider', 'match': 'openai', 'line': 20}`
- `{'file': 'tests/unit/test_b17_classifier_noop.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 23}`
- `{'file': 'tests/unit/test_b17_classifier_noop.py', 'kind': 'db', 'match': 'psycopg2', 'line': 25}`
- `{'file': 'tests/unit/test_b17_classifier_noop.py', 'kind': 'db', 'match': 'asyncpg', 'line': 26}`
- `{'file': 'tests/unit/test_b17_content_extraction_noop.py', 'kind': 'provider', 'match': 'anthropic', 'line': 18}`
- `{'file': 'tests/unit/test_b17_content_extraction_noop.py', 'kind': 'provider', 'match': 'openai', 'line': 19}`
- `{'file': 'tests/unit/test_b17_content_extraction_noop.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 23}`
- `{'file': 'tests/unit/test_b17_content_extraction_noop.py', 'kind': 'db', 'match': 'psycopg2', 'line': 25}`
- `{'file': 'tests/unit/test_b17_content_extraction_noop.py', 'kind': 'db', 'match': 'asyncpg', 'line': 26}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'provider', 'match': 'anthropic', 'line': 192}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'provider', 'match': 'openai', 'line': 192}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'provider', 'match': 'anthropic', 'line': 193}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'provider', 'match': 'openai', 'line': 193}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'db', 'match': 'psycopg2', 'line': 192}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 192}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'db', 'match': 'psycopg2', 'line': 193}`
- `{'file': 'tests/unit/test_b17_repository_embedding_health_adapter.py', 'kind': 'db', 'match': 'sqlalchemy', 'line': 193}`
Fresh base high-signal hits:
- `{'file': 'memory_lab/reasoning/answer.py', 'kind': 'private_prompt_or_ip', 'match': 'private_prompt', 'line': 28}`
- `{'file': 'memory_lab/reasoning/answer.py', 'kind': 'private_prompt_or_ip', 'match': 'private prompt', 'line': 136}`
- `{'file': 'memory_lab/reasoning/explain.py', 'kind': 'private_prompt_or_ip', 'match': 'private_prompt', 'line': 22}`

## 9. Readiness recommendation

`ready_for_fresh_live_remote_reapplication_gate`

## 10. Exactly one next safe gate

`GO_B17_FRESH_LIVE_REMOTE_REAPPLICATION_IMPLEMENTATION`

## Caveats

- A fresh clone was created/used only as a clean baseline; B17 files were not applied.
- The report files themselves are untracked audit artifacts in the fresh baseline after the precheck report is written.
- Future implementation must re-check live remote HEAD immediately before applying files.

## Final status

`B17_FRESH_CLONE_LIVE_REMOTE_REAPPLICATION_PRECHECK_PASS_WITH_CAVEATS`
