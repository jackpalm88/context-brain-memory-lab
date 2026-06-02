-- Migration: Add node_type column to content_items (Phase 4 — Node Type Layer)
-- Idempotent: safe to run multiple times.

ALTER TABLE content_items
  ADD COLUMN IF NOT EXISTS node_type VARCHAR(32) NOT NULL DEFAULT 'raw_note'
    CHECK (node_type IN (
      'decision', 'fact', 'hypothesis', 'question', 'playbook',
      'concept', 'source', 'task', 'event', 'raw_note'
    ));

CREATE INDEX IF NOT EXISTS idx_content_items_node_type ON content_items (node_type);
