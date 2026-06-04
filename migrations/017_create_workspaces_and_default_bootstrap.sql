-- 017_create_workspaces_and_default_bootstrap.sql
-- Prestage 3 P3A2: workspace registry foundation.
-- Scope: additive schema only; no runtime isolation claim.
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS cb_workspaces (
    workspace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_subject TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cb_workspaces_one_default
    ON cb_workspaces (is_default)
    WHERE is_default = TRUE;

CREATE INDEX IF NOT EXISTS idx_cb_workspaces_status
    ON cb_workspaces (status);

INSERT INTO cb_workspaces (slug, title, status, is_default, created_by_subject)
VALUES ('default', 'Default Workspace', 'active', TRUE, 'local-dev-default-subject')
ON CONFLICT (slug) DO UPDATE
SET title = EXCLUDED.title,
    status = 'active',
    is_default = TRUE,
    updated_at = NOW();
