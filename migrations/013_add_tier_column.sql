-- Migration: Phase 7b — Tier Routing
-- Idempotent: safe to run multiple times.

-- Create the memory_tier ENUM
-- Note: decision_artifact is set ONLY by create_decision_memory router (human gate).
-- The tier_router MUST NEVER auto-assign decision_artifact from scoring alone.
DO $$ BEGIN
    CREATE TYPE memory_tier AS ENUM (
        'transient',
        'probationary',
        'persistent',
        'decision_artifact',
        'conflicted',
        'superseded',
        'decayed',
        'archived'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Tier columns on content_items
ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS tier             memory_tier,
    ADD COLUMN IF NOT EXISTS tier_assigned_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tier_reason      TEXT,
    ADD COLUMN IF NOT EXISTS retrieval_count  INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_retrieved_at TIMESTAMPTZ;

-- Backfill: all existing content was saved under old permissive standard — treat as persistent
-- Run in small batches to avoid locking issues on large tables
UPDATE content_items
   SET tier             = 'persistent',
       tier_assigned_at = created_at,
       tier_reason      = 'backfill:pre_phase7b'
 WHERE tier IS NULL;

-- Index for decay queries (7d prerequisite)
CREATE INDEX IF NOT EXISTS idx_tier_decay
    ON content_items(tier, updated_at DESC)
    WHERE tier IN ('transient', 'probationary', 'persistent');

-- Index for retrieval filtering (default search excludes transient + archived)
CREATE INDEX IF NOT EXISTS idx_tier_search
    ON content_items(tier)
    WHERE tier NOT IN ('transient', 'archived');

-- Index for probationary TTL scans (7d uses tier_assigned_at)
CREATE INDEX IF NOT EXISTS idx_probationary_ttl
    ON content_items(tier_assigned_at)
    WHERE tier = 'probationary';
