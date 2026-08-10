# MCP_PARITY_TABLE.md — Tool-level MCP Parity Audit (production CB → Memory Lab public)

Status: parity CLOSED at 32/32 (2026-06-28, through M8E). Sections below are the original read-only audit plus appended M7-M8E outcome notes; the public surface now matches production.
Method: ground truth from source AND the live connected `context-brain-v2` MCP client.

UPDATE (2026-07-08, CF-003): the public surface is now **33** — `list_current_state_anchors`
(`GET /v1/current-state/anchors`) is the first public-only tool with NO production counterpart.
It is a kernel evolution driven by the Reference Framework consumer (CF-003:
cb_current_state_anchors was written but never publicly readable), not a parity item.
Production remains at 32; parity of the shared 32 is unchanged.

UPDATE (2026-07-08, CF-002 Stage 1): public surface **34** — `list_decisions_for_content`
(`GET /decisions/by-content/{content_id}`) is the second public-only tool, minted by the
same CF loop (CF-002: the decision↔content link existed in the schema — content_id column,
source_content_ids array — but was never publicly readable in the content→decision
direction). Production remains at 32.

## Counts (verified)

| Surface | Count | Evidence |
|---|---|---|
| Production MCP (private hosted Context Brain `mcp_server.py`) | **32** `@mcp.tool()` | grep == live client == 32 |
| Public MCP (`/opt/cbml/memory_lab/mcp/server.py`) | **18** registered (`APPROVED_TOOLS`) | server.py lines 13–30 |

NOTE: prior docs/handoffs said production exposes "36" — that is stale. Verified count is **32**.
The "8 / 11" earlier figures for public were the frozen-v1 plan (8) and an early PR1b smoke (11);
the current registered public surface is **18**.

FINAL (2026-06-28): after M7-M8E the public registered surface is now **32** (= production 32). The 18 above was the audit-time baseline.

## Exposed in both — 16 (9 renamed core + 7 decision tools, identical names)

| Production tool | Public MCP tool |
|---|---|
| health_check | memory_lab_health |
| search_raw_chunks | memory_lab_retrieval_search |
| get_content_by_id | memory_lab_content_get |
| create_hub | memory_lab_hub_create |
| get_hub | memory_lab_hub_get |
| link_content_to_hub | memory_lab_hub_link_content |
| create_hub_edge | memory_lab_edge_create |
| list_hub_edges | memory_lab_edge_list |
| archive_hub_edge | memory_lab_edge_archive |
| create_decision_memory | create_decision_memory |
| explain_decision | explain_decision |
| list_decisions | list_decisions |
| update_decision_status | update_decision_status |
| get_decision_lineage | get_decision_lineage |
| list_decision_conflicts | list_decision_conflicts |
| get_decision_timeline | get_decision_timeline |

Public-only additions (2): `memory_lab_content_create_id`, `memory_lab_edge_get`.

## The 16-tool gap — classified by backend evidence

| Prod tool | Class | Public backend evidence |
|---|---|---|
| query_memory | expose-only | api/routers/ask.py + reasoning/answer.py (provider opt-in) |
| list_hubs | expose-only | graph/hub_store.py:list_hubs + api/routers/hubs.py:list_hubs |
| update_hub | expose-only | graph/hub_store.py:update_hub + api/routers/hubs.py:update_hub |
| update_hub_edge | expose-only | graph/hub_edge_store.py:update_edge (no router yet) |
| approve_inferred_edge | expose-only | graph/hub_edge_store.py:approve_inferred_edge:184 |
| reject_inferred_edge | expose-only | graph/hub_edge_store.py:reject_inferred_edge:207 |
| save_and_link_to_hub | expose-only | composite of existing content-create + hub-link |
| get_graph_snapshot | expose-only (thin adapter) | graph/repository_reader.py + reports/graph_health_report.py |
| list_graph_snapshot | expose-only (thin adapter) | graph/repository_reader.py |
| load_graph_node_full | expose-only (thin adapter) | graph/repository_reader.py + content get |
| search_graph_preview | expose-only (thin adapter) | graph/repository_reader.py (preview wrapper needed) |
| set_quick_summary | IMPLEMENT | quick_summary is upsert-only column; no setter endpoint/service |
| update_node_metadata | IMPLEMENT | no public metadata-update backend |
| classify_content_node | IMPLEMENT (done M8E) | NOT provider — deterministic caller-specified node-type setter; `node_type` column already existed (no migration) |
| list_hubs_json | DROP | JSON-format variant; MCP transport already JSON |
| get_hub_json | DROP | JSON-format variant; MCP transport already JSON |

Tally: ~11 expose-only (incl. 4 thin-adapter), 3 implement (1 post-1.0), 2 drop.

## Proposed milestones (NOT executed — awaiting GO)

- **M7 — expose-only batch**: register existing backends as MCP tools
  (query_memory, list_hubs, update_hub, update_hub_edge, approve/reject_inferred_edge,
  save_and_link_to_hub, get/list_graph_snapshot, load_graph_node_full, search_graph_preview).
  Low risk: no new business logic, only MCP wrappers (+ thin router adapters for the graph reads).
- **M8 — implement gap**: set_quick_summary, update_node_metadata; classify_content_node deferred post-1.0 (provider).
- **Dropped by decision**: list_hubs_json, get_hub_json.

## Fix-forward corrections required
- PARITY_AUDIT.md "MCP server tool surface" row says post-1.0/"not implemented" — false; PR1b ships 18 MCP tools. (Corrected.)
- BLK-07 / handoff "36" production tools — actual is 32. (Corrected in CB + handoff.)


## M8D2 update — graph snapshot filter parity (2026-06-28)

Decision: real filters + keep alias. Implemented in commit (M8D2).

- `get_graph_snapshot(include_inferred, include_curated)` — **now functional**, and an
  INTENTIONAL PUBLIC IMPROVEMENT over production. Production accepts `include_inferred`
  but treats it as a documented no-op ("signals intent ... currently returns only
  curated"). Public contract: `include_inferred` returns **machine-generated**
  relationships, `include_curated` returns **human-curated** relationships. Both default
  True (backward compatible); both False → no edges. (Implementation note, NOT part of the
  contract: machine-generated currently = edge `origin` in `{inferred_approved,
  ai_suggested}`; curated = everything else. New origins can be added without changing the
  contract.) Rejected/archived edges remain excluded (reader-level). Stats now expose
  `curated_edge_count` + `inferred_edge_count`; response carries the applied `filters`.
- `list_graph_snapshot` — kept as a **flag-forwarding alias** of `get_graph_snapshot`
  (production parity: it is a pure alias / "spec-canonical name" in production; a distinct
  paginated surface would be invented, not parity).

Status change: `get_graph_snapshot` was "expose-only (thin adapter)" with non-functional
filters → now **full + improved**. `list_graph_snapshot` redundancy is **intentional
parity**, not a defect.


## Final status — 32/32 tool-count parity reached (2026-06-28)

Public MCP `APPROVED_TOOLS` now registers **32** tools = production's 32. Progression:
- **M7** — 11 expose-only tools registered (18 -> 29).
- **M8A** — `set_quick_summary` (real setter) + `update_node_metadata` (read-only metadata reader) (29 -> 31).
- **M8D1** — `save_and_link_to_hub` now persists `quick_summary`; `update_node_metadata` marked
  `read_only=true` / `mutation=none` (honest contract; no count change).
- **M8D2** — `get_graph_snapshot` real `include_inferred`/`include_curated` filters (intentional public
  improvement); `list_graph_snapshot` kept as alias (no count change).
- **M8E** — `classify_content_node` (31 -> 32): deterministic, caller-specified node-type setter. NOT
  AI/provider; response carries `deterministic=true`, `provider_backed=false`,
  `classification_mode="caller_specified"`, `allowed_node_types`. `node_type` column already existed; no migration.

CORRECTION to the 16-gap table above: `classify_content_node` was provisionally marked
"IMPLEMENT (post-1.0) / provider classifier". The M8E audit proved that wrong — production
`classify_content_node` is a deterministic node-type setter (`PATCH /content/{id}/node-type`),
not provider-backed. It shipped deterministically in M8E.

Confirmed DROPPED (intentional, not gaps): `list_hubs_json`, `get_hub_json` (JSON-format variants;
MCP transport is already JSON).

Parity character: this is not a blind copy of production. Where production parameters were no-ops or
names were misleading, the public version is more honest/functional and the divergence is documented as
intentional (graph snapshot filters; read-only metadata; deterministic classify). Remaining work is
deeper BEHAVIOR parity, tracked separately: `content_create_id` (minimal governed insert vs full
classify/dedup/embedding pipeline). `query_memory` behavior parity advanced under OPENCB-M11C-1: the
public ask path now returns a grounded answer with a declared `mode`
(`deterministic|provider_backed|degraded`), optional provider-backed wording behind a per-request
opt-in plus a deployment config gate (`MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED`), a citation
allow-list (no invented citations), and a typed degraded taxonomy. Still NOT private parity:
provider-derived confidence scoring and full semantic ranking remain private/provider territory.
OPENCB-M11C-2 later added a public `search_raw_chunks` analogue with retrieval envelope,
per-result diagnostics, and opt-in safe stage metrics; those diagnostics are descriptive
observability only and are not M12 ranking parity.


## M11C-2 update — raw retrieval MCP polish status (2026-07-01)

M11C-2 completed the public raw retrieval parity surface without claiming ranking parity:

- `memory_lab_retrieval_search` remains the public MCP analogue of production
  `search_raw_chunks`.
- `/v1/retrieval/search` accepts `query`, `limit`, `debug`, `only_clean`,
  `max_hops`, `min_confidence`, `graph_boost`, and API-level
  `memory_type`/`memory_types` filters.
- The MCP wrapper currently forwards `query`, `limit`, `debug`, `only_clean`,
  and `workspace_id`. API-level `memory_type`/`memory_types` filters are
  documented but are not added to the MCP wrapper in M11C-2-4 because that
  would be a tool-shape/behavior change, not documentation polish.
- `debug=false` keeps the normal response clean. `debug=true` exposes safe
  `debug_metadata.stage_metrics` for adapter search, normalize, deterministic
  retrieval, pgvector, hub inclusion, graph expansion, dedup/filtering counts,
  and degraded reasons.
- Per-result diagnostics include provenance, retrieval path/reason, ranking
  reason, hub/graph matches, knowledge path, score components, and distance
  when available.

Boundary: M11C-2 diagnostics are descriptive observability. They do not change
retrieval behavior, scoring, provider behavior, graph expansion, or ranking.
M12 ranking parity remains a separate future milestone.
