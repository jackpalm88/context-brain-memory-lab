-- migrations/022_create_auth_subjects.sql
-- Create the stable internal subject registry used by future auth adapters and service-agent identity.
-- This migration is additive only.

CREATE TABLE IF NOT EXISTS auth_subjects (
    auth_subject_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('human', 'service_agent')),
    external_provider TEXT NULL,
    external_subject TEXT NULL,
    display_name TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
