# M11B4 Context-Pack Integration Audit

Status: audit-only
Scope constraints: no product code changes, no commit, no push
Audited commit context: current `/opt/cbml` working tree after M10.3 push

## Goal

Determine how `QueryService` can use context-pack ownership internally without changing `/v1/ask` or MCP behavior.

The key architectural target is not to replace the public `/v1/ask` response with the public B12/B14 reasoning response. The target is to let `QueryService.execute` build or own a context-pack-shaped internal evidence container after retrieval, then project that container back into the exact existing `AskResponse` contract.

## Audited surfaces

### QueryService.execute current flow

File: `memory_lab/query/service.py`

Current flow:

1. Normalize public request query via `AskRequest.normalized_query()`.
2. Detect intent with `detect_intent(query)`.
3. Build retrieval policy via `policy_for_intent(detection.intent, request.top_k)`.
4. Call `RetrievalAdapter.search(...)` with fixed public ask retrieval kwargs:
   - `query=query`
   - `max_hops=1`
   - `min_confidence=0.0`
   - `graph_boost=0.1`
   - `workspace_id=workspace_id`
5. Normalize the first `policy.top_k` rows with `normalize_evidence(..., limit=policy.snippet_char_limit)`.
6. Call `synthesize_answer(...)` with `EvidenceItem` list.
7. Return public `AskResponse`.

Existing unit tests assert this exact behavior in `tests/unit/test_query_service.py`:

- `test_query_service_matches_previous_inline_ask_orchestration`
- `test_query_service_preserves_retrieval_kwargs`
- `test_query_service_preserves_degraded_no_evidence_behavior`

### ContextPackBuilder / build_context_pack_for_request

Files:

- `memory_lab/context_packs/models.py`
- `memory_lab/context_packs/builder.py`
- `memory_lab/context_packs/service.py`

Current context-pack builder path already uses the neutral canonical evidence layer:

- `build_context_pack_for_request` performs retrieval through `RetrievalAdapter.search`.
- It normalizes retrieval rows through `memory_lab.query.evidence.normalize_evidence`.
- It enriches support evidence with content metadata from `content_items` and `cb_current_state_anchors`.
- It optionally fetches current-state rows.
- It optionally searches conflict candidates.
- It delegates assembly to `build_context_pack`.

`build_context_pack` owns:

- deterministic ordering
- stable `context_pack_id`
- support/current/stale/counterfinding buckets
- warnings/non-claims
- include flags and source-service metadata
- evidence role assignment: `support`, `current_state`, `counterfinding`, stale/superseded signals

Important: `build_context_pack_for_request` is DB-owning and richer than `/v1/ask`. Directly routing `/v1/ask` through it would add current-state/conflict queries unless disabled, and may change retrieval parameters/limits unless carefully mapped.

### answer_context_pack

File: `memory_lab/reasoning/answer.py`

`answer_context_pack` consumes a `ContextPackBuildResponse`, collects evidence refs via `collect_evidence_refs`, builds traversal steps, builds conflict warnings, produces a deterministic `answer_candidate`, and optionally attempts provider wording only when explicitly enabled and globally allowed.

This path is for `/v1/reasoning/answer`, not `/v1/ask`:

- public response is `ReasoningAnswerResponse`, not `AskResponse`
- top-level field is `answer_candidate`, not `answer`
- evidence refs are dictionaries from context-pack refs, not `EvidenceItem` objects
- provider metadata / traversal / limitations / non-claims are public B14 fields, not `/v1/ask` fields

Therefore `/v1/ask` should not call `answer_context_pack` directly in M11B4 if the no-behavior-change rule is strict.

### normalize_evidence usage

`normalize_evidence` now lives in `memory_lab/query/evidence.py` and is re-exported from `memory_lab/reasoning/answer_synthesizer.py` for backward compatibility.

Observed callers:

- `QueryService.execute`
- `build_context_pack_for_request`
- `/v1/retrieval/search` router
- tests around canonical evidence normalization and retrieval evidence contract

This is a good seam: M11B4 can keep `normalize_evidence` as the single conversion from raw retrieval rows to `EvidenceItem`, then build a context pack from those already-normalized items. That avoids a second DB retrieval and avoids changing retrieval behavior.

### evidence_refs / citations mapping

Current `/v1/ask` citation mapping is in `synthesize_answer`:

- each `EvidenceItem` becomes a `Citation`
- citation fields: `evidence_id`, `rank`, `content_id`, `chunk_id`, `score`
- claims cite `EvidenceItem.evidence_id`
- answer text embeds `[evidence_id] snippet`

Current context-pack evidence mapping:

- `ContextPackEvidenceRef` includes `evidence_id`, `content_id`, `chunk_id`, `rank`, `snippet`, `score`, `score_kind`, current-state metadata, role, source, metadata
- `collect_evidence_refs` flattens support/current/counterfinding/stale buckets into dictionaries for reasoning endpoints

For `/v1/ask` parity, the safe path is to adapt only `context_pack.supporting_evidence` with role `support` back to `EvidenceItem`-equivalent objects before calling existing `synthesize_answer`.

### current-state handling

Current-state is present in context-pack construction and reasoning traversal, but it is not part of `/v1/ask` behavior today.

If QueryService builds an internal context pack for `/v1/ask` with `include_current_state=True`, the extra current-state refs must not affect `AskResponse.answer`, citations, evidence, claims, degraded status, confidence, or retrieval side effects. That is too risky for the smallest slice.

Smallest safe M11B4 should build a support-only internal context pack inside `QueryService`:

- `include_supporting_evidence=True`
- `include_current_state=False`
- `include_conflicts=False`
- `include_counterfindings=False`

For future M11 slices, current-state can be added as internal metadata only after explicit tests prove no public `/v1/ask` shape or content change, or after a separate public contract decision.

### retrieval result metadata

Raw retrieval rows currently preserve provenance through `normalize_evidence` metadata:

- `retrieval_mode`
- `retrieval_path`
- `embedding_status`
- `distance`
- `score_kind`

Context-pack refs preserve those fields through `evidence_from_item` / `_attach_provenance_metadata`, and can additionally hold memory classification/current-state metadata.

Missing for strict `/v1/ask` internal ownership is not metadata availability, but a formal adapter that guarantees round-trip projection:

`EvidenceItem -> ContextPackEvidenceRef(role=support) -> EvidenceItem`

without changing evidence IDs, ranks, snippets, scores, score kinds, retrieval paths, source/title, or metadata.

## Audit questions

### 1. Can QueryService build a ContextPack after retrieval without changing response shape?

Yes, with a support-only internal construction path.

The safest route is:

1. Keep QueryService retrieval exactly as-is.
2. Keep `normalize_evidence(results[:policy.top_k], limit=policy.snippet_char_limit)` exactly as-is.
3. Build a `ContextPackBuildRequest` from the ask query with `limit=policy.top_k` and all non-support include flags disabled.
4. Call lower-level `build_context_pack(...)`, not DB-owning `build_context_pack_for_request(...)`, using the already-normalized evidence.
5. Adapt `context_pack.supporting_evidence` back into `EvidenceItem` objects.
6. Call existing `synthesize_answer(...)` unchanged.

This makes ContextPack the internal ownership container without changing `/v1/ask` public response shape or retrieval query behavior.

Avoid in smallest slice:

- calling `build_context_pack_for_request` from QueryService, because it performs its own retrieval and can fetch current-state/conflicts
- calling `answer_context_pack`, because it returns `ReasoningAnswerResponse`, not `AskResponse`
- including current-state/conflicts in `/v1/ask`, because existing ask parity does not include those signals

### 2. What fields are missing from ContextPack for /v1/ask parity?

`ContextPackEvidenceRef` lacks explicit top-level fields required to reconstruct `EvidenceItem` perfectly:

- `retrieval_path` is not a top-level `ContextPackEvidenceRef` field; it is preserved in `metadata` and/or `source`
- `title` is not a top-level `ContextPackEvidenceRef` field; it may be absent after conversion unless preserved in metadata

`EvidenceItem` fields needed by `synthesize_answer`:

- `evidence_id`
- `rank`
- `content_id`
- `chunk_id`
- `snippet`
- `score`
- `score_kind`
- `retrieval_path`
- `source`
- `title`
- `metadata`

For current code behavior, `synthesize_answer` materially uses `evidence_id`, `rank`, `content_id`, `chunk_id`, `snippet`, and `score`. However, no-behavior-change should preserve the full `EvidenceItem` model dump because tests compare exact response evidence when `include_evidence=True`.

Recommended missing-field handling for M11B4:

- Adapter should derive `retrieval_path` from `ref.metadata["retrieval_path"]`, else `ref.source`, else `"deterministic_db"`.
- Adapter should preserve `title` if present in `ref.metadata["title"]`; if current builder does not preserve title, update only internal metadata attachment in the adapter/builder path with tests.
- Alternatively, avoid lossy conversion by carrying original `EvidenceItem` list alongside the support-only context pack in an internal wrapper. This gives ownership to context pack while preserving exact ask evidence projection.

### 3. Can existing synthesize_answer consume ContextPack evidence, or does it need an adapter?

It needs an adapter.

`synthesize_answer` expects `list[EvidenceItem]`; context-pack reasoning functions expose `ContextPackEvidenceRef` models or dictionaries. Passing context-pack refs directly would couple `/v1/ask` to B12/B14 models and risks losing `retrieval_path`/`title` details.

Smallest adapter options:

- `evidence_items_from_context_pack(context_pack) -> list[EvidenceItem]`, support refs only.
- `supporting_evidence_to_items(refs) -> list[EvidenceItem]`, lower-level and easier to unit test.
- Internal wrapper object, e.g. `QueryContextPack`, containing both `context_pack` and `ask_evidence`; this is safest for exact parity but introduces a second internal model.

Recommendation: implement a narrow adapter in the neutral query layer, not in reasoning:

- `memory_lab/query/context_pack_adapter.py`
- converts support refs to `EvidenceItem`
- does not expose new public API
- has round-trip unit tests

### 4. Which tests prove no behavior change?

Minimum no-behavior-change tests:

1. Existing `tests/unit/test_query_service.py` must remain unchanged or be expanded to compare old inline flow to new context-pack-backed flow.
2. Add unit test: support-only context-pack projection round-trips `EvidenceItem.model_dump()` exactly for representative rows containing:
   - chunk id
   - score
   - score_kind
   - retrieval_path
   - source
   - title
   - metadata provenance
3. Add unit test: `QueryService.execute` still calls retrieval adapter once with the same kwargs currently asserted in `test_query_service_preserves_retrieval_kwargs`.
4. Add unit test: `QueryService.execute` does not include current-state/conflict refs in ask synthesis by default.
5. Add unit test: empty retrieval still returns identical degraded insufficient-evidence `AskResponse`.
6. Integration/API test for `/v1/ask` response shape and exact field set, proving no `context_pack_id`, `context_pack_ref`, `answer_candidate`, `traversal_steps`, `provider_metadata`, or B14 fields leak into ask.
7. MCP parity tests for ask/query tool outputs, if the MCP server routes through `/v1/ask` or QueryService. The assertion should be public shape unchanged, not internal object existence.

Existing related tests to keep green:

- `tests/unit/test_query_service.py`
- `tests/unit/test_retrieval_evidence_contract.py`
- `tests/unit/test_canonical_evidence_normalization.py`
- `tests/unit/test_context_pack_builder.py`
- `tests/unit/test_reasoning_answer.py`
- `tests/unit/test_reasoning_answer_endpoint_stub.py`
- `tests/integration/test_context_pack_api.py`
- `tests/integration/test_reasoning_answer_api.py`

### 5. What is the smallest M11B4 implementation slice?

Recommended smallest slice:

1. Add a neutral internal helper that builds a support-only context pack from already-normalized QueryService evidence:
   - input: `AskRequest`, `workspace_id`, `query`, `policy`, `evidence`
   - output: `ContextPackBuildResponse`
   - uses `build_context_pack`, not `build_context_pack_for_request`
   - all non-support include flags disabled
2. Add an adapter from `context_pack.supporting_evidence` back to `EvidenceItem`.
3. Change `QueryService.execute` only enough to insert this internal ownership step between normalization and `synthesize_answer`:
   - retrieval unchanged
   - detection/policy unchanged
   - synthesis unchanged
   - returned `AskResponse` unchanged
4. Add tests proving old inline response equals new context-pack-backed response.
5. Do not expose `context_pack_id` in `/v1/ask` yet.
6. Do not include current-state/conflict ownership in `/v1/ask` yet.
7. Do not change MCP behavior.

## Recommended implementation plan

### Phase 1: support-only ownership seam

- Create query-layer adapter/helper with no public router changes.
- Build support-only context pack after existing retrieval normalization.
- Project support refs back to `EvidenceItem` for existing `synthesize_answer`.
- Keep old public response unchanged.

### Phase 2: parity locks

- Expand QueryService unit tests to compare exact `AskResponse.model_dump()` between old inline and new context-pack-backed path.
- Add adapter round-trip tests.
- Add public `/v1/ask` shape test asserting no reasoning/context-pack fields leak.
- If MCP uses QueryService, add/retain MCP output shape parity tests.

### Phase 3: future optional enrichment, not M11B4 smallest slice

- Consider current-state as internal metadata only after separate audit/GO.
- Consider canonical query/retrieval plan metadata after current-state risk is isolated.
- Consider letting `synthesize_answer` accept an abstract evidence protocol only after public ask parity is locked.

## Recommendation

Proceed with M11B4 implementation only as a support-only internal context-pack ownership seam. Do not route `/v1/ask` through `build_context_pack_for_request` or `answer_context_pack` in this slice.

This preserves the architecture principle: public behavior remains stable while internal ownership moves toward context pack as the canonical evidence container.
