---
name: opencb-memory
description: Save, link, and retrieve knowledge in Context Brain Memory Lab (OpenCB). Use when the user asks to remember something, recall prior context/decisions, link content to hubs, or search the workspace memory. Covers the daily read/write loop over the REST API and MCP tools.
---

# OpenCB Memory — daily save/query loop

Context Brain Memory Lab is a workspace-scoped, governed memory: every save is
scored and tiered, classified, current-state-resolved, and conflict-checked.
Retrieval is ranked by composite Scoring Model v2. Nothing you save becomes
"curated truth" without the human gate.

## Connection

- REST API: `http://127.0.0.1:8088` (docker compose default) or `:8000` (dev_run_api.sh).
  Auth: `Authorization: Bearer <api key>` + optional `X-Workspace-ID: <uuid>`.
  The compose stack runs in local_dev_bypass mode — no key needed there.
- MCP (stdio): `python -m memory_lab.mcp.server` — 32 approved tools.
- MCP (streamable-http): `python -m memory_lab.mcp.http_server` (Bearer auth).

## Save (write path)

`POST /v1/content {"content": "..."}` — MCP: `save_and_link_to_hub`.

The response tells you what governance did; read it, don't assume:

- `persisted: false, mode: governed_discarded` — content scored below the tier
  gate. Low-signal one-liners are dropped by design; write substantive notes.
- `duplicate: true` — same content_hash already exists in this workspace.
- `tier` — transient/probationary/persistent…; `memory_type` + `classify_confidence`.
- `conflict_escalation_id` (when present) — the save contradicted existing
  memory; `conflict_severity: requires_review` means the row is quarantined at
  `tier: conflicted` until a human approves/rejects the escalation (see the
  opencb-ops skill).

Explicit conflict markers in the text drive deterministic conflict detection:
lines like `contradicts: <claim>`, `counterfinding: <...>`, `supports: <...>`.

## Retrieve (read path)

- `POST /v1/retrieval/search {"query": "..."}` — MCP: `search_raw_chunks`.
  Each result carries `confidence`, `result_trust` (high/medium/low),
  `ranking_reason`, `source_path` (semantic/hub_linked/mixed/graph_neighbor)
  and `score_components`. The response-level `ranking_signals` says which
  boosts fired. Trust `low` = weak evidence — corroborate before relying on it.
- `POST /v1/ask` — MCP: `query_memory` — evidence-grounded answer envelope.
- `POST /v1/conflicts/search` — MCP: `list_decision_conflicts` /
  `search_conflict_candidates` — computed contradiction candidates (read-only,
  no truth arbitration).

## Organize (hubs & graph)

- Create hub: `POST /v1/hubs {"title", "type", "aliases", "related_terms"}` —
  MCP: `create_hub`. Good aliases/related_terms directly improve both ranking
  corroboration and inferred-edge quality.
- Link content: `POST /v1/hubs/{hub_id}/links {"content_id"}` — MCP:
  `link_content_to_hub`. Manual links earn a fixed +0.15 recall boost.
- Edges between hubs: `POST /v1/edges` (manual) — machine-proposed edges appear
  as `status: inferred` and need `POST /v1/edges/inferred/approve|reject`
  (MCP: `approve_inferred_edge` / `reject_inferred_edge`).

## Decisions

- `POST /v1/decisions` — MCP: `create_decision_memory` — first-class decision
  nodes with lineage; `explain_decision`, `get_decision_lineage`,
  `get_decision_timeline` for the reasoning surface.

## Rules of thumb

1. Save prose with enough signal to survive the tier gate; include `decision:`
   /`finding:` vocabulary when recording decisions or findings.
2. Always check the save response for `conflict_escalation_id` and surface it
   to the user instead of silently continuing.
3. Prefer hub-linking important content right after saving — curation is a
   ranked signal, not just organization.
4. When retrieval trust is `low`, say so; don't present weak evidence as fact.
