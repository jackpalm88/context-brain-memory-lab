-- Migration 006: Hub Edge Layer for Cognitive Map
-- Phase: Cognitive Map Layer — Phase 2 (Hub Edge Backend v1)
-- Date: 2026-05-10
--
-- Adds cb_hub_edges table to persist curated hub-to-hub relationships.
-- Inferred edges are computed at runtime; only human curation decisions are persisted here.
-- This migration is idempotent — safe to run multiple times.

CREATE TABLE IF NOT EXISTS cb_hub_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_hub_id   UUID NOT NULL REFERENCES cb_hubs(hub_id) ON DELETE CASCADE,
    target_hub_id   UUID NOT NULL REFERENCES cb_hubs(hub_id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN (
                        'parent', 'related', 'duplicate', 'overlaps',
                        'supports', 'part_of', 'contradicts'
                    )),
    status          TEXT NOT NULL CHECK (status IN (
                        'manual', 'approved', 'rejected', 'needs_review', 'archived'
                    )),
    origin          TEXT NOT NULL CHECK (origin IN (
                        'manual', 'inferred_approved', 'inferred_rejected',
                        'ai_suggested', 'migration_localStorage'
                    )),
    confidence      REAL CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    reason          TEXT,
    note            TEXT,
    -- Deterministic dedup key: sorted(src,tgt)|type for symmetric, src|tgt|type for directional
    edge_key        TEXT NOT NULL,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cb_hub_edges_source
    ON cb_hub_edges(source_hub_id);

CREATE INDEX IF NOT EXISTS idx_cb_hub_edges_target
    ON cb_hub_edges(target_hub_id);

CREATE INDEX IF NOT EXISTS idx_cb_hub_edges_status
    ON cb_hub_edges(status);

-- Prevents duplicate active edges for the same hub pair+type.
-- Archived edges are excluded (archived_at IS NULL).
CREATE UNIQUE INDEX IF NOT EXISTS idx_cb_hub_edges_key_active
    ON cb_hub_edges(edge_key)
    WHERE archived_at IS NULL;

COMMENT ON TABLE cb_hub_edges IS 'Persisted hub-to-hub relationships (curated). Inferred edges are computed at runtime.';
COMMENT ON COLUMN cb_hub_edges.edge_key IS 'Deterministic key: sorted(src,tgt)|type for symmetric types, src|tgt|type for directional.';
COMMENT ON COLUMN cb_hub_edges.archived_at IS 'Set when edge is archived; enables edge_key reuse for new edge.';
