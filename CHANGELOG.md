# Changelog

## 0.2.0a1 — M4

- Hardened reasoning answer citation/provenance behavior for `/v1/reasoning/answer`.
- Stabilized public evidence-ID citations so answer candidates cite supplied evidence refs rather than ordinal placeholders.
- Added opt-in provider-backed `/v1/reasoning/answer` synthesis behind `MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED` and request-level `enable_provider_synthesis`.
- Kept provider-backed synthesis disabled by default with deterministic evidence-grounded fallback behavior.
- Preserved safe fallback on disabled, missing, degraded, or rejected provider output, including invented citations and forbidden truth/verdict/resolution language.
- Added endpoint-level stub verification for provider-disabled, request opt-in, fake-provider success, invented-citation rejection, and forbidden-term rejection paths.

## 0.2.0a1 — M3

- Added gated pgvector retrieval path for opt-in vector KNN search.
- Added embedding write seam to `PostgresPersistenceBackend` after chunk insert.
- Preserved deterministic retrieval fallback as the default and degraded/no-key path.
- Added migration `032_add_m3_pgvector_knn_index.sql` for the M3 pgvector KNN index and embedding metadata.
- Added live pgvector stub test coverage proving vector similarity ranking over recency ordering.

## 0.2.0a1 — M2

- Added `PostgresPersistenceBackend` for opt-in DB-backed content and governance persistence.
- Enabled explicit Postgres selection through `DATABASE_URL` / `CB_TEST_DATABASE_URL` while preserving deterministic empty-env behavior.
- Kept `InMemoryPersistenceBackend` as the empty-env fallback and explicit no-DB seam.
- Verified live throwaway Postgres round-trip coverage for content save→load, governance state save→load, and governance event append→list.
- Added migration `031_add_m2_persistence_roundtrip.sql` for the M2 persistence round-trip schema support.

## 0.2.0a1 — M1

- Froze the B-scheme milestone baseline for Context Brain Memory Lab.
- Established `/opt/cbml` as the canonical working tree and aligned project state pointers.
- Preserved deterministic, read-only graph-health API behavior without requiring `DATABASE_URL`.
- Kept DB-backed write/admin/provider paths fail-closed when database or key prerequisites are absent.
- Restored full hermetic test compatibility under the installed FastAPI route include behavior.
- Reconciled the package version to `0.2.0a1` for the M1 freeze candidate.
