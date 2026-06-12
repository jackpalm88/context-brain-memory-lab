-- Migration: Discovered Domains Registry — workspace-level domain registry
-- Phase: 7b  Owner: classify pipeline  Idempotent: safe to run multiple times.
-- NOTE: Distinct from freetext content_items.domain (legacy). This is the governed registry.

CREATE TABLE IF NOT EXISTS cb_discovered_domains (
    domain_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    domain_name  TEXT NOT NULL,
    description  TEXT,
    source       TEXT NOT NULL DEFAULT 'auto_classify'
                 CHECK (source IN ('auto_classify', 'manual', 'imported')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, domain_name)
);

CREATE INDEX IF NOT EXISTS idx_domains_workspace
    ON cb_discovered_domains(workspace_id);

-- FK on content_items: links content to its classified domain
ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS domain_id UUID
        REFERENCES cb_discovered_domains(domain_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_content_domain_id
    ON content_items(domain_id)
    WHERE domain_id IS NOT NULL;
