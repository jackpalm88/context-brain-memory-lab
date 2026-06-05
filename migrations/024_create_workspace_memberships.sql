-- migrations/024_create_workspace_memberships.sql
-- Create the subject-to-workspace authorization bridge for static RBAC roles.
-- This migration is additive only and does not enforce roles at runtime.

CREATE TABLE IF NOT EXISTS workspace_memberships (
    membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES cb_workspaces(workspace_id),
    auth_subject_id UUID NOT NULL REFERENCES auth_subjects(auth_subject_id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'writer', 'reader', 'service_agent', 'auditor')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'invited', 'suspended', 'revoked')),
    created_by_subject_id UUID NULL REFERENCES auth_subjects(auth_subject_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, auth_subject_id)
);
