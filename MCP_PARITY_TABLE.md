# MCP_PARITY_TABLE.md — Tool-level MCP Parity Audit (production CB → Memory Lab public)

Status: AUDIT (read-only findings). No tools added/removed by this document.
Method: ground truth from source AND the live connected `context-brain-v2` MCP client.

## Counts (verified)

| Surface | Count | Evidence |
|---|---|---|
| Production MCP (`/opt/contentingestor/mcp_server.py`) | **32** `@mcp.tool()` | grep == live client == 32 |
| Public MCP (`/opt/cbml/memory_lab/mcp/server.py`) | **18** registered (`APPROVED_TOOLS`) | server.py lines 13–30 |

NOTE: prior docs/handoffs said production exposes "36" — that is stale. Verified count is **32**.
The "8 / 11" earlier figures for public were the frozen-v1 plan (8) and an early PR1b smoke (11);
the current registered public surface is **18**.

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
| classify_content_node | IMPLEMENT (post-1.0) | provider classifier is opt-in/future |
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

Decision (Ritvars): real filters + keep alias. Implemented in commit (M8D2).

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
