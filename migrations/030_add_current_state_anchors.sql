-- Migration: Current State Anchors — authoritative supersession chain for current-state discipline
-- Phase: 7d  Owner: current-state system (NOT classify pipeline)  Idempotent: safe to run multiple times.
-- Mirrors cb_decision_nodes.supersedes_decision_id pattern (migration 011).
-- INVARIANT: current-state system NEVER writes memory_type or project_topic (classify pipeline owns those).
-- NOTE: is_current here != is_active_classification in cb_classification_history (migration 027).
-- NULL semantics for is_current: NULL=unscoped/not-yet-evaluated, FALSE=superseded, TRUE=active anchor.

CREATE TABLE IF NOT EXISTS cb_current_state_anchors (
    anchor_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id          UUID NOT NULL,
    memory_type           TEXT NOT NULL
                          CHECK (memory_type IN (
                              'milestone', 'decision', 'principle', 'anchor',
                              'evidence', 'plan_roadmap', 'raw_memory')),
    scope                 TEXT NOT NULL,
    content_id            UUID REFERENCES content_items(content_id) ON DELETE SET NULL,
    supersedes_content_id UUID REFERENCES content_items(content_id) ON DELETE SET NULL,
    valid_from            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until           TIMESTAMPTZ,
    canonical_rank        INTEGER NOT NULL DEFAULT 1
                          CHECK (canonical_rank >= 0),
    state_status          TEXT NOT NULL DEFAULT 'active'
                          CHECK (state_status IN ('active', 'superseded', 'archived')),
    state_reason          TEXT,
    set_by                TEXT NOT NULL DEFAULT 'auto_classify'
                          CHECK (set_by IN (
                              'auto_classify', 'human_override', 'mcp_tool', 'api', 'reconcile_job')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Active anchors per workspace + type + scope (hot path: current_only=True filter)
CREATE INDEX IF NOT EXISTS idx_anchor_workspace_type_scope
    ON cb_current_state_anchors(workspace_id, memory_type, scope)
    WHERE state_status = 'active';

-- Reverse lookup: content_id → anchor record
CREATE INDEX IF NOT EXISTS idx_anchor_content_id
    ON cb_current_state_anchors(content_id)
    WHERE content_id IS NOT NULL;

-- Supersession chain traversal
CREATE INDEX IF NOT EXISTS idx_anchor_supersedes
    ON cb_current_state_anchors(supersedes_content_id)
    WHERE supersedes_content_id IS NOT NULL;

-- Denormalized current-state columns on content_items (hot retrieval path — avoids JOIN)
ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS is_current               BOOLEAN DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS current_state_scope      TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS cs_supersedes_content_id UUID
        REFERENCES content_items(content_id) ON DELETE SET NULL;

-- is_current=TRUE filter (hot path for current_only=True retrieval)
CREATE INDEX IF NOT EXISTS idx_content_is_current
    ON content_items(is_current)
    WHERE is_current = TRUE;

-- Scope-based current-state filter
CREATE INDEX IF NOT EXISTS idx_content_current_state_scope
    ON content_items(current_state_scope)
    WHERE current_state_scope IS NOT NULL;
