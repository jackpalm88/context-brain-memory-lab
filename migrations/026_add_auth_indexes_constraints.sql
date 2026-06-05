-- migrations/026_add_auth_indexes_constraints.sql
-- Add secondary indexes for auth/RBAC schema foundation lookups.
-- Indexes are additive and idempotent.

CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_subjects_external_identity
    ON auth_subjects (external_provider, external_subject)
    WHERE external_provider IS NOT NULL AND external_subject IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auth_subjects_type_status
    ON auth_subjects (subject_type, status);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix_status
    ON api_keys (key_prefix, status);

CREATE INDEX IF NOT EXISTS idx_api_keys_subject_status
    ON api_keys (auth_subject_id, status);

CREATE INDEX IF NOT EXISTS idx_api_keys_last_used_at
    ON api_keys (last_used_at);

CREATE INDEX IF NOT EXISTS idx_workspace_memberships_subject_status
    ON workspace_memberships (auth_subject_id, status);

CREATE INDEX IF NOT EXISTS idx_workspace_memberships_workspace_role_status
    ON workspace_memberships (workspace_id, role, status);

CREATE INDEX IF NOT EXISTS idx_workspace_memberships_workspace_status
    ON workspace_memberships (workspace_id, status);

CREATE INDEX IF NOT EXISTS idx_cb_audit_events_created_at
    ON cb_audit_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cb_audit_events_workspace_created
    ON cb_audit_events (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cb_audit_events_subject_created
    ON cb_audit_events (auth_subject_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cb_audit_events_event_type_created
    ON cb_audit_events (event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cb_audit_events_decision_reason_created
    ON cb_audit_events (decision, reason_code, created_at DESC);
