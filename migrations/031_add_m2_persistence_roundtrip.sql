-- 031_add_m2_persistence_roundtrip.sql
-- M2: DB-backed persistence contract round-trip support.
-- Scope: additive schema in existing Context Brain directions:
-- - content_items/content_chunks for content persistence records
-- - cb_governance_states for current governance-state contract snapshots
-- - cb_governance_events append-only stream extended for B25 state events
-- No vector retrieval, provider, or LLM behavior.

ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS content_title TEXT,
    ADD COLUMN IF NOT EXISTS content_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS governance_state_id TEXT;

CREATE TABLE IF NOT EXISTS cb_governance_states (
    workspace_id   UUID NOT NULL,
    record_id      TEXT NOT NULL,
    record_type    TEXT NOT NULL,
    content_id     UUID REFERENCES content_items(content_id) ON DELETE SET NULL,
    status         TEXT NOT NULL CHECK (status IN ('draft', 'needs_review', 'active', 'archived', 'superseded', 'rejected')),
    tier           TEXT NOT NULL CHECK (tier IN ('discard', 'transient', 'probationary', 'persistent', 'decision_artifact', 'archived', 'conflicted', 'superseded', 'decayed')),
    provenance     JSONB NOT NULL DEFAULT '{}'::jsonb,
    supersedes     TEXT,
    superseded_by  TEXT,
    state_reason   TEXT,
    limitations    JSONB NOT NULL DEFAULT '[]'::jsonb,
    non_claims     JSONB NOT NULL DEFAULT '[]'::jsonb,
    mode           TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, record_id)
);

CREATE INDEX IF NOT EXISTS idx_governance_states_workspace_status
    ON cb_governance_states(workspace_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_governance_states_content
    ON cb_governance_states(content_id)
    WHERE content_id IS NOT NULL;

ALTER TABLE cb_governance_events
    ADD COLUMN IF NOT EXISTS record_id TEXT,
    ADD COLUMN IF NOT EXISTS previous_status TEXT,
    ADD COLUMN IF NOT EXISTS next_status TEXT,
    ADD COLUMN IF NOT EXISTS event_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'gov_events_event_type_check'
           AND conrelid = 'cb_governance_events'::regclass
    ) THEN
        ALTER TABLE cb_governance_events DROP CONSTRAINT gov_events_event_type_check;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'gov_events_event_type_check'
           AND conrelid = 'cb_governance_events'::regclass
    ) THEN
        ALTER TABLE cb_governance_events
            ADD CONSTRAINT gov_events_event_type_check
            CHECK (event_type IN ('tier_transition_v1', 'b25_data_only_governance_state_event_v1'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_gov_events_workspace_record
    ON cb_governance_events(workspace_id, record_id, created_at DESC)
    WHERE workspace_id IS NOT NULL AND record_id IS NOT NULL;
