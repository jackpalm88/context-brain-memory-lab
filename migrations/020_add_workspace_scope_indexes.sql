-- 020_add_workspace_scope_indexes.sql
-- Prestage 3 P3A2: workspace-scope indexes for later API/retrieval enforcement.
-- Scope: additive indexes only; indexes do not prove runtime isolation.
-- Idempotent: safe to run multiple times.

CREATE INDEX IF NOT EXISTS idx_content_items_workspace_created
    ON content_items(workspace_id, created_at DESC)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_content_items_workspace_tier_created
    ON content_items(workspace_id, tier, created_at DESC)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_content_chunks_workspace_content
    ON content_chunks(workspace_id, content_id)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_hubs_workspace_uuid_status
    ON cb_hubs(workspace_uuid, status)
    WHERE workspace_uuid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_hub_content_workspace_hub
    ON cb_hub_content(workspace_id, hub_id)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_hub_content_workspace_content
    ON cb_hub_content(workspace_id, content_id)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_hub_edges_workspace_status
    ON cb_hub_edges(workspace_id, status)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_aliases_workspace_term_status
    ON cb_aliases(workspace_id, LOWER(term), status)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_alias_candidates_workspace_status
    ON cb_alias_candidates(workspace_id, status)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_edges_workspace_from
    ON cb_edges(workspace_id, from_node)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cb_edges_workspace_to
    ON cb_edges(workspace_id, to_node)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_decision_nodes_workspace_status_created
    ON cb_decision_nodes(workspace_id, decision_status, created_at DESC)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_decision_nodes_workspace_supersedes
    ON cb_decision_nodes(workspace_id, supersedes_decision_id)
    WHERE workspace_id IS NOT NULL AND supersedes_decision_id IS NOT NULL;
