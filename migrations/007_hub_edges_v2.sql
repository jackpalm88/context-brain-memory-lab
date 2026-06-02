-- Migration 007: Hub edges v2 — add weight column, expand status, fix constraint
-- Date: 2026-05-10
-- Idempotent: safe to run multiple times.

-- Add weight column (layout hint, default 1.0)
ALTER TABLE cb_hub_edges ADD COLUMN IF NOT EXISTS weight REAL DEFAULT 1.0;

-- Expand status CHECK to include 'inferred' (for future inference job support)
ALTER TABLE cb_hub_edges DROP CONSTRAINT IF EXISTS cb_hub_edges_status_check;
ALTER TABLE cb_hub_edges ADD CONSTRAINT cb_hub_edges_status_check
    CHECK (status = ANY (ARRAY[
        'inferred'::text, 'manual'::text, 'approved'::text,
        'rejected'::text, 'needs_review'::text, 'archived'::text
    ]));

COMMENT ON COLUMN cb_hub_edges.weight IS 'Layout hint for force simulation. Default 1.0.';
