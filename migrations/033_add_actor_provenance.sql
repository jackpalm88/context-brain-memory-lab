-- migrations/033_add_actor_provenance.sql
-- M9B Provenance Completion: row-level authenticated-actor provenance.
-- Additive, nullable, idempotent. No backfill.
--
-- created_by_subject semantics:
--   NULL     = object predates provenance support OR creator is genuinely unknown
--   non-NULL = authenticated subject (auth_subject_id) persisted by the server
-- Historical rows intentionally remain NULL (we do not fabricate authorship).
ALTER TABLE content_items  ADD COLUMN IF NOT EXISTS created_by_subject TEXT;
ALTER TABLE cb_hubs        ADD COLUMN IF NOT EXISTS created_by_subject TEXT;
ALTER TABLE cb_hub_content ADD COLUMN IF NOT EXISTS created_by_subject TEXT;
