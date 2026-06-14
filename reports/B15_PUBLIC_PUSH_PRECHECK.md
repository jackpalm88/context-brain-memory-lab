# B15 Public Push Precheck

status: **B15_PUBLIC_PUSH_PRECHECK_PASS_WITH_CAVEATS**

gate: `B15_PUBLIC_PUSH_PRECHECK`

mode: precheck only — no commit, push, tag, release, PyPI upload, or CB write.

clean export: `/opt/context-brain-memory-lab_public_export_b15`

public repo: `https://github.com/jackpalm88/context-brain-memory-lab.git`

## Public repo state

- local path found: `/opt/context-brain-memory-lab_public_repo`
- local branch/head before and after fetch: `8d4eef3bdd55ed4ba47a416a42afe25e758cf8eb`
- remote `origin/main`: `97830f0828359e9bab79ce558e03494f9547ae1e`
- previous known B14 final public HEAD: `97830f0828359e9bab79ce558e03494f9547ae1e`
- B14 head matches `origin/main`: PASS
- local checkout caveat: behind `origin/main`; push execution must first fast-forward/reset to `origin/main`.
- existing B15 tag refs: none found
- GitHub release checks: `v0.1.0b15` HTTP 404, `0.1.0b15` HTTP 404

## Export readiness

- version `0.1.0b15`: PASS
- B15 source files present: PASS
- B15 tests present: PASS
- B15 reports present: PASS
- clean dist artifacts present and hashed: PASS
- README B15 endpoints/caveats/non-claims: PASS
- export file count: 199
- export bytes: 1151346

Artifact hashes:
- wheel: `68ddab56333541b78281f3fab6e3ce21eda58958d9d9eb580b68544b6124855d`
- sdist: `b1ec3ce309e2efccfc6cefcf9b4f50755eecb57da4ba57f65c064c86b1799699`

## Hygiene precheck

PASS with caveats.

- `.git`, `.env*`, `.venv`, caches, private/dev directories: absent
- only allowlisted B15 reports are present in `reports/`
- no private key/token/provider-key values found
- no private production source material found
- clean-export `dist/` entries are intentional rebuilt B15 artifacts

Caveats:
- B15_CLEAN_EXPORT_AND_BUILD_REVIEW.md contains allowed wording that states private production source material was absent; this is not source leakage.
- Public docs/code/tests include configuration identifier names for provider/API/database settings; no secret values were found.
- MISSING_API_KEY="***" placeholder is non-secret.
- dist artifacts are present because they were rebuilt inside the clean export.

## Validation precheck

- py_compile: PASS
- B15 targeted tests: `20 passed in 2.03s`
- broader API smoke: PASS
- artifact hash verification: PASS
- rebuild: not repeated; existing clean-export artifacts verified by sha256

## Push plan only

Expected commit message:

`Release 0.1.0b15 graph health and retrieval governance`

Base: `origin/main` at `origin/main at 97830f0828359e9bab79ce558e03494f9547ae1e`

Copy source: `/opt/context-brain-memory-lab_public_export_b15/`

Copy target: `/opt/context-brain-memory-lab_public_repo/ after fast-forward/reset to origin/main`

Diff plan versus `origin/main`:
- added: 23
- modified: 3
- removed: 10

Added files:
- `dist/context_brain_memory_lab-0.1.0b15-py3-none-any.whl`
- `dist/context_brain_memory_lab-0.1.0b15.tar.gz`
- `memory_lab/api/routers/graph_health.py`
- `memory_lab/graph/alias_hygiene.py`
- `memory_lab/graph/health_models.py`
- `memory_lab/graph/health_service.py`
- `memory_lab/graph/hub_recall_health.py`
- `memory_lab/reports/__init__.py`
- `memory_lab/reports/graph_health_report.py`
- `reports/B15_CLEAN_EXPORT_AND_BUILD_REVIEW.md`
- `reports/B15_GRAPH_HEALTH_REPORT_GENERATOR.md`
- `reports/B15_GRAPH_HEALTH_SERVICE_ONLY.md`
- `reports/B15_VERSION_DOCS_PREP.md`
- `reports/b15_clean_export_and_build_review_summary.json`
- `reports/b15_graph_health_report_generator_summary.json`
- `reports/b15_graph_health_service_only_summary.json`
- `reports/b15_version_docs_prep_summary.json`
- `scripts/b15_graph_health_report.py`
- `tests/integration/test_graph_health_api.py`
- `tests/smoke/test_b15_graph_health_report.py`
- `tests/unit/test_alias_hygiene_candidates.py`
- `tests/unit/test_graph_health_service.py`
- `tests/unit/test_hub_recall_health.py`

Modified files:
- `README.md`
- `memory_lab/api/main.py`
- `pyproject.toml`

Removed files:
- `dist/context_brain_memory_lab-0.1.0b14-py3-none-any.whl`
- `dist/context_brain_memory_lab-0.1.0b14.tar.gz`
- `reports/.gitkeep_public_export_review_note`
- `reports/B14_CLEAN_EXPORT_AND_BUILD_REVIEW.md`
- `reports/B14_CLEAN_EXPORT_VALIDATION.log`
- `reports/B14_PUBLIC_PUSH.md`
- `reports/B14_PUBLIC_PUSH_PRECHECK.md`
- `reports/b14_clean_export_and_build_review_summary.json`
- `reports/b14_public_push_precheck_summary.json`
- `reports/b14_public_push_summary.json`

## Scope guard

- git fetch only: PASS
- no commit: PASS
- no push: PASS
- no tag: PASS
- no GitHub release: PASS
- no PyPI upload: PASS
- no provider calls: PASS
- no DB/private CB access: PASS
- no graph mutation: PASS
- no CB write: PASS

## Final status

B15_PUBLIC_PUSH_PRECHECK_PASS_WITH_CAVEATS
