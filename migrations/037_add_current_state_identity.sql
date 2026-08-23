-- 037_add_current_state_identity.sql
-- Phase A: split current_state_scope (grouping) from state_identity (replacement key).
-- Ratified: decision 4a11008b-9ea8-4468-a305-328075349c9b (candidate #3), spec closed
-- through de24fac8-a7c5-435f-883a-b0350230a1f1 (implementation-readiness pass +
-- acceptance matrix). No relationship_type column — deliberately deferred to Phase B,
-- which hasn't decided where typed relationships should live.
--
-- state_identity is nullable and NEVER auto-backfilled from current_state_scope on
-- existing rows (see the Phase A migration plan: backfilling identity from a broad
-- scope value is the same mistake this whole change exists to fix, in a new column).
-- Existing rows keep state_identity = NULL, meaning "legacy, scope-keyed, not
-- authoritative for supersession" per the spec's read-path rule.

ALTER TABLE content_items
  ADD COLUMN IF NOT EXISTS state_identity TEXT;

ALTER TABLE cb_current_state_anchors
  ADD COLUMN IF NOT EXISTS state_identity TEXT;

-- Supersession lookups are keyed on (workspace_id, memory_type, state_identity) for
-- identity-bearing writes; index only the non-null subset (partial index — legacy
-- NULL rows never participate in this lookup).
CREATE INDEX IF NOT EXISTS idx_cb_current_state_anchors_identity
  ON cb_current_state_anchors (workspace_id, memory_type, state_identity)
  WHERE state_identity IS NOT NULL;
