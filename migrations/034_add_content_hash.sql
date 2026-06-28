-- migrations/034_add_content_hash.sql
-- M10.2 Content-level deduplication: SHA-256 hash of the submitted body.
-- Additive, nullable, idempotent. No backfill (historical rows stay NULL).
--
-- content_hash semantics:
--   NULL     = row predates content-level dedup OR body hash genuinely unknown
--   non-NULL = sha256(content) persisted by the server at create time
--
-- The partial unique index is the integrity backstop: the API does a
-- friendly check-before-insert, but the DB is the final authority against
-- races. NULL content_hash rows are excluded so legacy data is unaffected.
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ix_content_items_ws_content_hash
    ON content_items (workspace_id, content_hash)
    WHERE content_hash IS NOT NULL;
