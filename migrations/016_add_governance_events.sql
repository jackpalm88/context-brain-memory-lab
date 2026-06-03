-- Migration: Phase 7b T1/T1.5 — Governance Events
-- Append-only table for tier_transition_v1 events.
-- IMMUTABILITY INVARIANT: No UPDATE or DELETE paths exist in application code.
-- Rollback and override are represented by new events (additive-only).
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS cb_governance_events (
    event_id         UUID PRIMARY KEY,
    event_type       TEXT NOT NULL DEFAULT 'tier_transition_v1',
    content_id       UUID,            -- NULL for discard events (content never persisted)
    workspace_id     UUID,
    previous_tier    TEXT,        -- NULL for initial assignment
    new_tier         TEXT NOT NULL,
    transition_reason TEXT NOT NULL,
    transition_rule  TEXT NOT NULL,
    trigger_type     TEXT NOT NULL,   -- system | human_override | policy_engine
    trigger_source   TEXT NOT NULL,   -- save | classify | cleanup | admin | mcp
    trace_id         TEXT NOT NULL,
    scores           JSONB,           -- {quality, relevance, novelty, composite}
    lineage_ref      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT gov_events_trigger_type_check CHECK (
        trigger_type IN ('system', 'human_override', 'policy_engine')
    ),
    CONSTRAINT gov_events_trigger_source_check CHECK (
        trigger_source IN ('save', 'classify', 'cleanup', 'admin', 'mcp')
    ),
    CONSTRAINT gov_events_event_type_check CHECK (
        event_type = 'tier_transition_v1'
    )
);

-- Prevent accidental row-level mutations via DB trigger (belt-and-suspenders).
-- Application code must never issue UPDATE/DELETE on this table.
CREATE OR REPLACE FUNCTION cb_governance_events_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '[governance_events] IMMUTABILITY VIOLATION: UPDATE/DELETE on cb_governance_events is forbidden. '
        'Rollback and override must be represented as new events.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_governance_events_immutable ON cb_governance_events;
CREATE TRIGGER trg_governance_events_immutable
    BEFORE UPDATE OR DELETE ON cb_governance_events
    FOR EACH ROW EXECUTE FUNCTION cb_governance_events_immutable();

-- Indexes for audit queries by trace_id, content, and workspace
CREATE INDEX IF NOT EXISTS idx_gov_events_trace_id
    ON cb_governance_events(trace_id);

CREATE INDEX IF NOT EXISTS idx_gov_events_content_id
    ON cb_governance_events(content_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_gov_events_workspace
    ON cb_governance_events(workspace_id, created_at DESC)
    WHERE workspace_id IS NOT NULL;
