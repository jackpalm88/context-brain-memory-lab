-- migrations/035_add_content_tags.sql
-- M10.3 Optional semantic enrichment: topic & metadata annotations.
-- Additive, nullable (default empty array), idempotent. No backfill.
--
-- These columns are the STORAGE for semantic annotations produced by optional
-- enrichment. The public contract is "semantic annotations" at the concept
-- level; TEXT[] is today's storage and may later move to a governed tag
-- registry without changing the API. Enrichment is provider-gated with a
-- deterministic fallback, so these stay '{}' when no provider/key is present
-- and no keywords are extracted.
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS topic_tags TEXT[] DEFAULT '{}';
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS meta_tags  TEXT[] DEFAULT '{}';
