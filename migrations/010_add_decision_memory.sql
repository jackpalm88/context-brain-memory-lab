-- Migration: Decision Memory Primitives (Phase 6a)
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS cb_decision_nodes (
    decision_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id       UUID REFERENCES content_items(content_id) ON DELETE SET NULL,
    title            TEXT NOT NULL,
    decision_reason  TEXT NOT NULL,
    decision_context TEXT,
    why_this_matters TEXT,
    decision_status  TEXT NOT NULL DEFAULT 'active'
                     CHECK (decision_status IN ('active', 'superseded', 'reversed', 'draft')),
    reversible       BOOLEAN NOT NULL DEFAULT true,
    source_content_ids UUID[],
    linked_hub_ids   UUID[],
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decision_nodes_status  ON cb_decision_nodes(decision_status);
CREATE INDEX IF NOT EXISTS idx_decision_nodes_created ON cb_decision_nodes(created_at DESC);
