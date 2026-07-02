# EMB-1D — Semantic Loop Acceptance Report

Engineering Quality Asset. Validates the full save→chunk→embed→persist→retrieve chain
end-to-end against a live ephemeral pgvector/pg16 DB with a deterministic stub backend.
(No OpenAI key required — DeterministicStubBackend uses SHA-256 unit-normalized vectors.)

- Date: 2026-07-02 21:08 UTC
- Backend: DeterministicStubBackend (SHA-256 → 1536-dim unit-normalized, no network)
- DB: ephemeral pgvector/pg16, repo migrations applied
- Properties: E1 (save→find), E2 (chunk-level), E3 (ws isolation), E4 (graceful degradation), E5 (backfill)

## VERDICT: PASS (5/5 properties)

| Property | Label | Result | Detail |
|---|---|---|---|
| E1 | save→semantic find | PASS | saved content found=True, rank=1/1, top_distance=1.0398 |
| E2 | multi-chunk: correct fragment | PASS | closest chunk content_id_match=True, chunk_index=1 (expected 1), distance=0.00000000 (expected <1e-6 for exact-text query) |
| E3 | workspace isolation (semantic) | PASS | WS_B leaked into WS_A=False, WS_A leaked into WS_B=False, ws_a_result_count=5, ws_b_result_count=1 |
| E4 | no-embedding graceful degradation | PASS | no_embedding_stored=True, fallback_no_crash=True, found_via_deterministic=True |
| E5 | backfill → semantically findable | PASS | not_found_before_backfill=True, found_after_backfill=True, rank=6, backfill_stats=attempted:2/stored:2 |

## Semantic loop closure
- save → embed → persist: confirmed (E1)
- chunk-level retrieval: confirmed (E2)
- workspace isolation (semantic): confirmed (E3)
- graceful degradation (no embedding): confirmed (E4)
- backfill closes the loop: confirmed (E5)

## Scope note
DeterministicStubBackend produces structurally meaningful cosine similarities
(different text → different SHA-256 → different vector → genuine KNN ranking).
Production semantic quality depends on a real provider (OpenAI/equivalent);
this harness validates the plumbing, not the embedding model quality.
