-- migrations/036_add_dx2_feedback.sql
-- DX-2: feedback table for thumbs-up/thumbs-down signals on retrieved content.
-- Lightweight: no FK to content_items (items may be pruned); store content_id as TEXT.
-- Additive only — no existing tables modified.

CREATE TABLE IF NOT EXISTS cb_retrieval_feedback (
    feedback_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id    TEXT        NOT NULL,
    query_text    TEXT        NULL,
    signal        TEXT        NOT NULL CHECK (signal IN ('up', 'down')),
    workspace_id  UUID        NULL REFERENCES cb_workspaces(workspace_id) ON DELETE SET NULL,
    subject_id    TEXT        NULL,
    metadata      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cb_retrieval_feedback_content_id
    ON cb_retrieval_feedback (content_id);

CREATE INDEX IF NOT EXISTS idx_cb_retrieval_feedback_workspace_signal
    ON cb_retrieval_feedback (workspace_id, signal);
