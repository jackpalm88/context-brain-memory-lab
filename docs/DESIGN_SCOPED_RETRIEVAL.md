# Design: First-Class Scoped Retrieval

- **Status:** Accepted and implemented (Option B).
- **Grounded in commit:** `c8d2fcb3c6c758fb7cf31c15e0396e5a674916ce` (this repo, branch `main`, working tree clean at time of writing).
- **Triggered by:** Hermes "Specialist Isolation Phase 5 — Scoped OpenCB Projection" (`~/.hermes/control-plans-v0.1/SPECIALIST-ISOLATION-PHASE5-SCOPED-OPENCB-PROJECTION-20260904.json`), which needs to constrain `SpecialistContextBuilder` retrieval to specific hubs.
- **Not in scope:** any new persistence schema for subject/topic or sensitivity/policy scoping. Those are named as future extension axes only (see §8).

## 1. Problem statement

Phase 5 needs specialist agents (starting with the psychology-agent) to retrieve
only from hubs their manifest explicitly allows, with a receipted record of
what scope was applied. Today, OpenCB retrieval has no caller-supplied scoping
primitive narrower than `workspace_id` at all. The question is what shape that
primitive should take, given it will likely be reused by Agent Builder,
research ingestion, and handoff surfaces later.

## 2. Governance check — this touches the Graph Navigation scope freeze

`docs/ARCHITECTURE_BOUNDARIES.md` is binding post-v1.0 (repo tagged `v1.0.0`
at `4f6a100`, current state per `STATE.md`). Because `cb_hub_content` and the
hub-linked candidate path (`RetrievalAdapter._hub_linked_results`) are part of
the graph layer, this change must be evaluated against the freeze **before**
any implementation, not after.

Frozen-without-unfreeze-GO items relevant here: "new recall or ranking modes"
and "new graph traversal engines." A caller-supplied hub scope is **neither**
— it does not add a traversal engine, does not change what makes a candidate
admissible for scoring (the composite ranker's constants are untouched), and
does not treat hub adjacency as truth. It is a pre-scoring `WHERE`-clause
restriction on the candidate universe, structurally identical to the
already-shipped `workspace_id` and `memory_types` filters
(`memory_lab/api/services/retrieval_adapter.py`).

Running the five-point "Allowed under freeze" containment checklist
(`docs/ARCHITECTURE_BOUNDARIES.md`, precedent commit `678178e`):

1. **Read-only w.r.t. the graph** — yes. No writes to `cb_hubs` / `cb_hub_content` / `cb_hub_edges`.
2. **Operates inside an existing, already-shipped bounded mechanism** — yes. Reuses the existing `cb_hub_content(hub_id, content_id)` join and the three existing `WHERE`-clause builders; no new traversal path.
3. **Candidate admission stays governed by non-tunable module constants** — yes, with a distinction that must be stated explicitly in review: `CURATED_GRAPH_BOOST` / `MANUAL_LINK_BOOST` (`memory_lab/retrieval/composite_ranker.py`) remain fixed constants, exactly as today. A caller-supplied scope restricts *which rows enter the candidate set*, the same category of thing `workspace_id` and `memory_types` already do — it does not make *ranking* tunable. `RetrievalRequest.graph_boost`'s own docstring already draws this line: "M12 curation boosts... are fixed constants... and are not caller-configurable" (`memory_lab/api/routers/retrieval.py`). Scope filtering must preserve that line, not blur it.
4. **Opt-in per surface; non-opted callers are byte-identical** — must hold by construction (see §5, §7): omitting scope must produce the exact response shape and candidate set as today.
5. **Honestly named** — call it "scoped retrieval" / `retrieval_scope`, not "traversal" or "reasoning."

All five hold for both options below, so **this can proceed as a standard boundary-compliant change** — it does not require the full boundary-amendment procedure (root cause + owner GO naming the frozen item). If review disagrees with point 3's framing, that disagreement should block implementation, not be argued around.

## 3. Option A — narrow `hub_ids` pre-filter

Add a single new parameter, `hub_ids: Optional[List[str]]`, following the
exact shape of `memory_types` today.

**Where:** three `WHERE`-clause builders in `retrieval_adapter.py`
(`_deterministic_vector_search`, `_pgvector_knn_search`, `_hub_linked_results`),
each gaining:

```python
if hub_ids:
    where_parts.append(
        "c.content_id = ANY(SELECT content_id FROM cb_hub_content WHERE hub_id = ANY(%s::uuid[]))"
    )
    params.append(list(hub_ids))
```

(or an explicit `JOIN cb_hub_content hc ON hc.content_id = c.content_id AND hc.hub_id = ANY(%s::uuid[])` — subquery vs. join is an implementation-time choice, not a design fork.)

**Pros:** smallest possible diff; directly unblocks Phase 5; trivially satisfies the freeze checklist.

**Cons:** single-purpose parameter. `content_types` scoping already exists under a different name (`memory_types`) with its own mutual-exclusivity validation (`retrieval.py`); adding `hub_ids` as a third, differently-shaped, unrelated parameter means a *second* migration is likely later when Agent Builder or research ingestion need both "these hubs" and "these content types" scoped together, or when `subject_scope`/`policy_scope` eventually arrive — at that point either three-plus independent list params accumulate on `RetrievalRequest`, or someone reshapes `hub_ids` into a wrapper object anyway, breaking the Option A contract.

## 4. Option B — additive `retrieval_scope` abstraction (recommended)

Introduce one optional structured field that wraps what already exists, plus
reserved-but-unimplemented keys for future axes:

```python
retrieval_scope: Optional[RetrievalScope] = None

class RetrievalScope(BaseModel):
    allowed_hubs: Optional[List[str]] = None      # implemented now — wraps hub_ids
    content_types: Optional[List[str]] = None      # implemented now — alias for memory_types
    # Reserved, NOT implemented in this change. No backing schema exists.
    # subject_scope: Optional[List[str]] = None
    # policy_scope: Optional[List[str]] = None
```

`content_types` is not new capability — it is `memory_types` under the
`retrieval_scope` envelope, so a caller can express "these hubs AND these
memory types" as one scope object instead of two independent top-level
params. `memory_type`/`memory_types` stay as-is at the top level for
backward compatibility (see §5); `retrieval_scope.content_types`, if both are
given, must be validated as equivalent-or-conflicting the same way
`memory_type` vs `memory_types` already is, just one level deeper.

**Pros:** matches the codebase's own established convention (list-of-values
pre-scoring filter, same `WHERE`-builder mechanism) instead of inventing a
new one; gives every future consumer (Agent Builder, research ingestion,
handoffs) one contract to target instead of accreting parallel filter
params; the reserved-but-empty `subject_scope`/`policy_scope` keys let the
*shape* be settled now without committing to schema that doesn't exist yet
(§8 explicitly forbids designing that schema here).

**Cons:** marginally larger surface than Option A (one new Pydantic model,
one new MCP parameter shape instead of a bare list); slightly more validation
code (cross-field equivalence between `retrieval_scope.allowed_hubs` and any
future bare `hub_ids`, if one is ever added — it should not be, precisely to
avoid this).

## 5. Recommendation

**Option B, constrained to stay additive and small.** It satisfies the same
freeze checklist as Option A (§2) with no larger blast radius — the same
three `WHERE`-builders change, no new tables, no new indexes, no ranking
changes — and it avoids a predictable second migration. The condition for
this recommendation, matching the instruction that scope must not widen into
governance/schema work: `retrieval_scope` in this change implements **only**
`allowed_hubs` and `content_types`, both backed by columns/junction tables
that already exist and are already indexed (§6.3). `subject_scope` and
`policy_scope` are reserved field names with no accessor, no validation, and
no schema — see §8.

## 6. Detailed design (Option B)

### 6.1 Candidate-generation touchpoints

All three candidate sources in `RetrievalAdapter.search()`
(`memory_lab/api/services/retrieval_adapter.py`) honor scope identically,
applied **before** scoring, not after:

- **pgvector path** (`_pgvector_knn_search`, used when `_query_embedding()` succeeds) — the hub join/subquery and `content_types` (already `memory_types`) join its existing `where_parts`.
- **deterministic/lexical path** (`_deterministic_vector_search`, used as fallback and unconditionally appended "alongside pgvector") — same addition to its `where_parts`.
- **hub-linked path** (`_hub_linked_results`) — this one is subtle: it does its own single-hub, query-text-matched lookup via `HubStore.match_query`, independent of any caller scope. Under `retrieval_scope.allowed_hubs`, this path's candidate hub is intersected with `allowed_hubs` (if the query-matched hub is not in the allowed set, it contributes zero hub-linked candidates for this call) — it does not silently ignore scope just because its matching mechanism is different from the other two paths.

`rank_by_composite()` (`memory_lab/retrieval/composite_ranker.py`) itself does
not change — scope is a candidate-set restriction applied before ranking sees
anything, exactly like `workspace_id` today.

### 6.2 SQL/query shape and index usage

`allowed_hubs` reuses `cb_hub_content(hub_id, content_id)` (PK,
`migrations/005_add_hub_layer.sql`) and the composite index
`idx_cb_hub_content_workspace_hub ON cb_hub_content(workspace_id, hub_id)`
(`migrations/020_add_workspace_scope_indexes.sql`). The join/subquery
filtering `c.content_id::text = ANY(SELECT content_id FROM cb_hub_content
WHERE hub_id = ANY(%s::uuid[]))` (note: `cb_hub_content.content_id` is `TEXT`,
not `UUID` — the existing `HubStore.get_hub_content_ids` join already casts
the other direction, `hc.content_id::uuid`; this design casts `c.content_id`
to `text` to match the junction table's native type instead) is covered by
that index. **No new index or migration is required** for `allowed_hubs`.
`content_types` needs no new index either; it reuses the existing
`memory_type` filter mechanism verbatim.

This SQL shape is also what makes fail-closed semantics (§6.5) fall out
structurally rather than requiring special-case code: an `ANY(subquery)`
over an empty or non-matching result set evaluates to `FALSE` for every
candidate row, so a nonexistent hub, a zero-content hub, or a hub outside the
caller's workspace (excluded transitively by the pre-existing
`c.workspace_id = %s` clause, which still combines via `AND`) all naturally
yield zero candidates from that source — with no dedicated "hub not found"
branch to get wrong.

### 6.3 Backward compatibility for existing workspace-wide callers

`retrieval_scope` is `Optional`, default `None`. Every existing call site
(`memory_lab/mcp/tools.py`; `memory_lab/api/routers/retrieval.py`, `ask.py`;
`memory_lab/query/service.py`) passed no scope before this change and
continues to produce byte-identical responses when it continues to pass
none — this is checklist point 4 in §2, enforced by regression tests that
assert the adapter's private search methods receive `allowed_hubs=None` and
produce the same SQL/param shape as before when no scope is supplied (see
§9).

### 6.4 API + MCP contract changes

- `RetrievalRequest` (`memory_lab/api/routers/retrieval.py`) gains
  `retrieval_scope: Optional[RetrievalScope] = None`, validated the same way
  `memory_type`/`memory_types` are validated today (`_validate_memory_type_filter`)
  plus a sibling validator for scope-vs-legacy-field conflicts.
- `AskRequest` (`memory_lab/reasoning/models.py`) gains the same field and
  the same validator, since `QueryService.execute()`
  (`memory_lab/query/service.py`) calls the same `RetrievalAdapter.search()`.
- `memory_lab_retrieval_search` MCP tool (`memory_lab/mcp/tools.py`) gains an
  optional `retrieval_scope: Optional[Dict[str, Any]]` parameter, forwarded
  through the MCP client to the REST body.
- `query_memory` MCP tool (`memory_lab/mcp/tools.py`) — same addition.
- `search_graph_preview` is **out of scope for this change**. It is a
  separate, simpler SQL path (`memory_lab/api/services/api_adapter.py`) that
  already takes a single `hub_id` as an *annotation* (not a filter, per its
  `LEFT JOIN` use); folding it into `retrieval_scope` semantics is a second,
  later change, not bundled here.

### 6.5 Fail-closed semantics

When `retrieval_scope` is explicitly supplied but unresolvable (e.g.
`allowed_hubs` names a hub id that doesn't exist, or resolves to zero
content, or the workspace mismatch makes it inaccessible), the request
**returns zero candidates for that source, not an unscoped fallback.** This
mirrors Phase 5's own stated failure mode ("missing manifest
`scope_contracts` → projections marked `denied_due_to_missing_scope`... no
silent fallback", `agent/specialist_context_builder.py` Phase 5 docstring).
As described in §6.2, this is a structural property of the `ANY(subquery)`
shape, not a branch that could be accidentally skipped.

### 6.6 Audit/provenance changes

- **`/v1/ask`** already writes to `cb_audit_events` via `record_ask_event`
  (`memory_lab/query/ask_audit.py`, called from `memory_lab/query/service.py`).
  Its `metadata` dict gains two new keys: `requested_scope` (the raw
  `retrieval_scope` the caller sent, or `null`) and `scope_enforcement`
  (`"pre_filter"` — always this value under this design, since scope is
  never applied post-hoc; the field is still worth recording so a future
  post-hoc code path can't silently regress provenance truthfulness without
  the audit record admitting it).
- **`/v1/retrieval/search`** writes **no audit record at all**. This is a
  pre-existing gap, not introduced by this change. A durable audit-write for
  raw retrieval was scoped as optional for the Phase 5 integration and was
  **not implemented in this change** — `scope_applied` on the response (§6.7)
  is the provenance surface for that endpoint instead. Adding a durable audit
  row for `/v1/retrieval/search` remains a tracked follow-up, not a blocker.

### 6.7 Response metadata / receipt representation

A `scope_applied` block is added to the response envelope, present exactly
when `retrieval_scope` was supplied (not gated behind `debug=true`, since
this is provenance, not internal diagnostics):

```json
"scope_applied": {
  "allowed_hubs": ["<uuid>", ...],
  "content_types": ["decision", ...],
  "enforcement": "pre_filter"
}
```

`content_types` in this block reflects the actual effective filter
(`resolved_content_types()` — merged from `retrieval_scope.content_types`
and/or legacy `memory_type`/`memory_types`, whichever was actually enforced),
not merely an echo of the raw request field.

This is the field Phase 5's `SpecialistContextBuilderScopedProjectionReceipt`
(`agent/specialist_context_builder.py`) should read to populate its own
`selection_method` / `claimed_equivalence_to_ranked_scoped` receipt fields
from OpenCB's actual behavior, rather than asserting it independently.

### 6.8 Performance implications

`allowed_hubs` join cost is bounded by hub membership cardinality against an
existing composite index — no measurable regression expected for typical hub
sizes (§6.2; no new index, no new table scan pattern). `content_types` has
zero incremental cost since it's the existing `memory_types` mechanism. The
only new cost is one extra `WHERE`/subquery fragment string-built into three
already-dynamic queries — the same pattern `memory_types` already adds today.

## 7. Test coverage

Precedent followed directly: `tests/unit/test_retrieval_memory_type_filter.py`
(existing, structurally identical feature). New coverage lives in
`tests/unit/test_retrieval_scope.py` and includes: `RetrievalScope` model
validation; `RetrievalRequest`/`AskRequest` cross-field validation against
legacy `memory_type`(s) (equivalent constraints coexist, contradictory ones
fail validation); SQL/param construction proving the hub subquery and its
params are added only when `allowed_hubs` is supplied, and combine with
`memory_types` via `AND`; `_hub_linked_results` scope-intersection gating
(including that an out-of-scope match short-circuits before the content
lookup); `RetrievalAdapter.search()` threading `allowed_hubs` into all three
candidate sources with a byte-identical `None` default; router-level
`scope_applied` provenance and 422 on conflicting scope-vs-legacy filters;
MCP client/tool forwarding; and `/v1/ask` audit `requested_scope` recording,
including through `QueryService.execute()`. Pre-existing regression suites
(`test_hub_recall_health.py`, `test_b19_deterministic_hub_detection.py`,
`test_b20_deterministic_knn_retrieval.py`, `test_mcp6_retrieval_meta_behavioral_contracts.py`,
`test_query_service.py`) were re-verified green; three had fixed-signature
fake adapters that needed the same additive `allowed_hubs=None` parameter
their real counterparts gained (the same category of update they already
needed when `memory_types` was added).

## 8. Explicitly out of scope

`subject_scope` and `policy_scope` are named in the `RetrievalScope` model as
comments/reserved keys only. No table, column, tagging mechanism, or
validation is designed or implemented for them here — a repo-wide search
confirms no existing `sensitivity`, `policy_scope`, or `subject_scope`
concept exists anywhere in `memory_lab/**/*.py`. Designing that persistence
model is a separate future design doc with its own governance review, not a
rider on this change.

## 9. Rollout / migration strategy

1. No DB migration required (§6.2, §6.3) — this ships as an application-layer
   change only.
2. `RetrievalScope` model + validator + the three `WHERE`-builder changes
   land together with this doc, citing the §2 freeze-checklist pass.
3. `scope_applied` response field ships with this change; the separate
   durable audit-write path for raw `/v1/retrieval/search` (§6.6) does not
   and remains a tracked, non-blocking follow-up.
4. `memory_lab/mcp/tools.py` and `memory_lab/mcp/client.py` signatures are
   updated in the same change.
5. `memory_lab/mcp/capability_manifest.yaml` and `docs/CAPABILITIES.md` are
   updated per the "envelope convention" doctrine
   (`ARCHITECTURE_BOUNDARIES.md` doctrine 6) — `scope_applied` is a
   materially changed surface and is documented machine-readably.
6. No flag/toggle needed beyond "scope is optional and additive" itself —
   there is no behavior change for callers who don't opt in, so there is
   nothing to gate behind a rollout flag.

## 10. Hermes Specialist Isolation Phase 5 — exact integration contract

Phase 5's `SpecialistContextBuilder.build_scoped_projection_receipt()`
(`agent/specialist_context_builder.py`), once this ships:

- Passes `retrieval_scope={"allowed_hubs": scope_contracts.allowed_hub_ids}`
  (derived from the manifest, as it does today) into
  `memory_lab_retrieval_search` / `query_memory` calls, instead of any
  bespoke client-side post-filtering.
- Reads `scope_applied` (§6.7) back from the OpenCB response to populate its
  own receipt's `selection_method` and set
  `claimed_equivalence_to_ranked_scoped` based on whether OpenCB actually
  applied `enforcement: "pre_filter"` — i.e. Phase 5's receipt asserts
  provenance it can verify from OpenCB's own response, not restate its
  request as if it were proof of enforcement.
- Its existing fail-closed behavior (`use_legacy_unscoped=False` → deny by
  default, no silent fallback) is already consistent with §6.5 and needs no
  change — this design's fail-closed semantics were written to match Phase
  5's existing contract, not the other way around.
- `_phase5_resolve_selection_method`'s existing distinction between
  `hub_ids filter on memory_lab_retrieval_search (preferred)` and
  `hub_linkage_enumeration via hub_get + content_get (degraded alternative)`
  maps directly: with this shipped, the "preferred" path becomes real and
  available.

## Sources verified against commit `c8d2fcb3c6c758fb7cf31c15e0396e5a674916ce`

`memory_lab/api/services/retrieval_adapter.py`,
`memory_lab/api/routers/retrieval.py`, `memory_lab/api/routers/ask.py`,
`memory_lab/query/service.py`, `memory_lab/query/ask_audit.py`,
`memory_lab/retrieval/composite_ranker.py`, `memory_lab/graph/hub_store.py`,
`memory_lab/mcp/tools.py`, `migrations/005_add_hub_layer.sql`,
`migrations/018_add_nullable_workspace_scope_core.sql`,
`migrations/020_add_workspace_scope_indexes.sql`,
`migrations/025_create_audit_events.sql`, `docs/ARCHITECTURE_BOUNDARIES.md`,
`STATE.md`, `tests/unit/test_retrieval_memory_type_filter.py`.
