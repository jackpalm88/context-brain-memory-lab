-- 015_escalation_ttl_severity.sql
-- Phase 7c hardening: severity-based TTL for escalations
-- warning       → 7 days  (CB_ESCALATION_TTL_WARNING_DAYS)
-- requires_review → 30 days (CB_ESCALATION_TTL_REQUIRES_REVIEW_DAYS)
--
-- The expires_at column already exists (migration 014).
-- This migration adds a partial index for efficient orphan queries
-- and a CHECK constraint so no escalation can have NULL expires_at.

ALTER TABLE cb_escalations
    ALTER COLUMN expires_at SET NOT NULL;

-- Fast lookup for "pending escalations that have expired" (used by status check + future decay job)
CREATE INDEX IF NOT EXISTS idx_escalations_pending_expired
    ON cb_escalations(expires_at)
    WHERE status = 'pending';
