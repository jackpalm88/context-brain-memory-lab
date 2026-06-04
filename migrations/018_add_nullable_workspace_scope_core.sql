-- 018_add_nullable_workspace_scope_core.sql
-- Prestage 3 P3A2: add nullable workspace scope columns to approved tables.
-- Scope: additive schema only; no backfill, no NOT NULL tightening.
-- Compatibility: preserve cb_hubs.workspace_id TEXT; add transitional workspace_uuid.
-- Idempotent: safe to run multiple times.

ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE content_chunks
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

-- Existing cb_hubs.workspace_id is TEXT in the public baseline. Do not cast/drop/rename it.
ALTER TABLE cb_hubs
    ADD COLUMN IF NOT EXISTS workspace_uuid UUID;

ALTER TABLE cb_hub_content
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE cb_hub_edges
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE cb_edges
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE cb_edges
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'workspace';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cb_edges_scope_check'
    ) THEN
        ALTER TABLE cb_edges
            ADD CONSTRAINT cb_edges_scope_check
            CHECK (scope IN ('workspace', 'global'));
    END IF;
END $$;

ALTER TABLE cb_aliases
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE cb_aliases
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'workspace';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cb_aliases_scope_check'
    ) THEN
        ALTER TABLE cb_aliases
            ADD CONSTRAINT cb_aliases_scope_check
            CHECK (scope IN ('workspace', 'global'));
    END IF;
END $$;

ALTER TABLE cb_alias_candidates
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE cb_alias_candidates
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'workspace';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cb_alias_candidates_scope_check'
    ) THEN
        ALTER TABLE cb_alias_candidates
            ADD CONSTRAINT cb_alias_candidates_scope_check
            CHECK (scope IN ('workspace', 'global'));
    END IF;
END $$;

ALTER TABLE cb_decision_nodes
    ADD COLUMN IF NOT EXISTS workspace_id UUID;

ALTER TABLE cb_decision_nodes
    ADD COLUMN IF NOT EXISTS created_by_subject TEXT;
