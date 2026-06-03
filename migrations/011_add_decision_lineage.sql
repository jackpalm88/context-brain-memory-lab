-- Migration: Decision Reasoning Layer (Phase 6b)
-- Idempotent: safe to run multiple times.

ALTER TABLE cb_decision_nodes
  ADD COLUMN IF NOT EXISTS supersedes_decision_id     UUID REFERENCES cb_decision_nodes(decision_id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS superseded_by_decision_id  UUID REFERENCES cb_decision_nodes(decision_id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS alternatives_considered    JSONB DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS contradicting_evidence     TEXT,
  ADD COLUMN IF NOT EXISTS confidence_level           TEXT DEFAULT 'medium'
      CHECK (confidence_level IN ('low', 'medium', 'high')),
  ADD COLUMN IF NOT EXISTS decision_tags              TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_decision_supersedes
    ON cb_decision_nodes(supersedes_decision_id)
    WHERE supersedes_decision_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_decision_superseded_by
    ON cb_decision_nodes(superseded_by_decision_id)
    WHERE superseded_by_decision_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_decision_tags
    ON cb_decision_nodes USING GIN(decision_tags);
