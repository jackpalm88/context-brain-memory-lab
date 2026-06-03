-- Migration: Phase 7a — Ingestion Scoring
-- Idempotent: safe to run multiple times.

-- Scoring columns on content_items
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS quality_score    FLOAT;
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS relevance_score  FLOAT;
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS novelty_score    FLOAT;
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS composite_score  FLOAT;
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS score_confidence FLOAT;
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS circuit_open     BOOLEAN DEFAULT FALSE;

-- DB-backed circuit breaker state (Pitfall #5 prevention)
CREATE TABLE IF NOT EXISTS cb_circuit_state (
    service     TEXT PRIMARY KEY,
    opened_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

-- Ingestion event log (Constitution Section 7: Observable)
CREATE TABLE IF NOT EXISTS cb_ingestion_log (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         UUID,
    content_id           UUID,
    event_type           TEXT NOT NULL,   -- 'scored' | 'tiered' | 'conflict_detected' | 'escalated' | 'persisted' | 'decayed'
    input_summary        TEXT,
    quality_score        FLOAT,
    relevance_score      FLOAT,
    novelty_score        FLOAT,
    composite_score      FLOAT,
    tier_decision        TEXT,
    conflict_detected    BOOLEAN DEFAULT FALSE,
    circuit_open         BOOLEAN DEFAULT FALSE,
    human_gate_triggered BOOLEAN DEFAULT FALSE,
    final_state          TEXT,
    reason               TEXT,
    applied_rule_ids     TEXT[],
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_log_content
    ON cb_ingestion_log(content_id, created_at DESC)
    WHERE content_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ingestion_log_workspace
    ON cb_ingestion_log(workspace_id, created_at DESC)
    WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ingestion_log_event_type
    ON cb_ingestion_log(event_type, created_at DESC);

-- Partial index for finding low-scored or circuit-open saves
CREATE INDEX IF NOT EXISTS idx_content_scoring
    ON content_items(composite_score, created_at DESC)
    WHERE composite_score IS NOT NULL;
