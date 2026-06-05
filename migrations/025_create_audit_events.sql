-- migrations/025_create_audit_events.sql
-- Create security/auth/admin audit event storage separate from governance tier events.
-- This migration is additive only and does not emit audit events by itself.

CREATE TABLE IF NOT EXISTS cb_audit_events (
    audit_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    auth_subject_id UUID NULL REFERENCES auth_subjects(auth_subject_id),
    workspace_id UUID NULL REFERENCES cb_workspaces(workspace_id),
    target_type TEXT NULL,
    target_id TEXT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny', 'error')),
    reason_code TEXT NULL,
    required_permission TEXT NULL,
    role TEXT NULL,
    request_id TEXT NULL,
    client_type TEXT NULL CHECK (client_type IS NULL OR client_type IN ('api', 'mcp', 'system', 'cli')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
