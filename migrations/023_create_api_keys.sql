-- migrations/023_create_api_keys.sql
-- Create the hash-only credential table for static API-key authentication.
-- Keys authenticate a subject; roles and workspace access remain membership/RBAC decisions.

CREATE TABLE IF NOT EXISTS api_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_subject_id UUID NOT NULL REFERENCES auth_subjects(auth_subject_id),
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    name TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'expired')),
    scopes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL,
    revoked_by_subject_id UUID NULL REFERENCES auth_subjects(auth_subject_id),
    last_used_at TIMESTAMPTZ NULL,
    CONSTRAINT api_keys_key_hash_unique UNIQUE (key_hash)
);
