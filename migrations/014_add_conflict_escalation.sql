-- 014_add_conflict_escalation.sql
-- Phase 7c: Conflict Detection + Human Escalation
-- Constitution Principles: III (Contradictions first-class), V (Human gate), VIII (Forgetting)

CREATE TABLE IF NOT EXISTS cb_escalations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     UUID NOT NULL,
    content_id       UUID REFERENCES content_items(content_id),
    conflict_content_id UUID REFERENCES content_items(content_id),
    conflict_type    TEXT NOT NULL,
    severity         TEXT NOT NULL DEFAULT 'requires_review',
    conflict_summary TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at       TIMESTAMPTZ DEFAULT NOW() + INTERVAL '4 hours',
    resolved_at      TIMESTAMPTZ,
    resolved_by      TEXT,

    CONSTRAINT cb_escalations_conflict_type_check CHECK (
        conflict_type IN (
            'same_topic', 'incompatible_assumption', 'direct_contradiction',
            'confidence_disagreement', 'outdated_assumption', 'no_conflict'
        )
    ),
    CONSTRAINT cb_escalations_severity_check CHECK (
        severity IN ('informational', 'warning', 'requires_review', 'hard_block')
    ),
    CONSTRAINT cb_escalations_status_check CHECK (
        status IN ('pending', 'approved', 'rejected', 'expired')
    )
);

CREATE INDEX IF NOT EXISTS idx_escalations_workspace
    ON cb_escalations(workspace_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_escalations_content
    ON cb_escalations(content_id);

CREATE INDEX IF NOT EXISTS idx_escalations_expiry
    ON cb_escalations(expires_at) WHERE status = 'pending';

ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS conflict_escalation_id UUID;
