-- Migration: Add quick_summary to content_items (Phase 5 — Quick Summary & Scoped Retrieval)
-- Idempotent: safe to run multiple times.

ALTER TABLE content_items
  ADD COLUMN IF NOT EXISTS quick_summary TEXT DEFAULT NULL;
