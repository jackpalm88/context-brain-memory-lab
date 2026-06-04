-- 019_backfill_default_workspace_scope.sql
-- Prestage 3 P3A2: backfill legacy single-tenant rows to the default workspace.
-- Scope: additive/backfill only; no deletes, no destructive casts, no NOT NULL tightening.
-- Idempotent: safe to run multiple times.

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE content_items
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

UPDATE content_chunks cc
SET workspace_id = ci.workspace_id
FROM content_items ci
WHERE cc.content_id = ci.content_id
  AND cc.workspace_id IS NULL
  AND ci.workspace_id IS NOT NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE content_chunks
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

-- Preserve cb_hubs.workspace_id TEXT. Use transitional workspace_uuid for UUID-scoped runtime later.
WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_hubs
SET workspace_uuid = (SELECT workspace_id FROM default_workspace)
WHERE workspace_uuid IS NULL;

UPDATE cb_hub_content hc
SET workspace_id = h.workspace_uuid
FROM cb_hubs h
WHERE hc.hub_id = h.hub_id
  AND hc.workspace_id IS NULL
  AND h.workspace_uuid IS NOT NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_hub_content
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

UPDATE cb_hub_edges e
SET workspace_id = src.workspace_uuid
FROM cb_hubs src
WHERE e.source_hub_id = src.hub_id
  AND e.workspace_id IS NULL
  AND src.workspace_uuid IS NOT NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_hub_edges
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_edges
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_aliases
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_alias_candidates
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;

WITH default_workspace AS (
    SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1
)
UPDATE cb_decision_nodes
SET workspace_id = (SELECT workspace_id FROM default_workspace)
WHERE workspace_id IS NULL;
