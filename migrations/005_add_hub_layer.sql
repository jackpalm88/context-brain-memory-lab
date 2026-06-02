-- Migration 005: Hub Layer for knowledge navigation
-- Hubs are user-defined or AI-suggested entry points; never auto-generated defaults.

CREATE TABLE IF NOT EXISTS cb_hubs (
    hub_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title         TEXT NOT NULL,
    type          TEXT NOT NULL DEFAULT 'topic'
                      CHECK (type IN ('project', 'system', 'concept_cluster', 'topic')),
    description   TEXT,
    aliases       TEXT[] NOT NULL DEFAULT '{}',
    related_terms TEXT[] NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'archived')),
    owner_defined BOOLEAN NOT NULL DEFAULT TRUE,
    workspace_id  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cb_hubs_title     ON cb_hubs (LOWER(title));
CREATE INDEX IF NOT EXISTS idx_cb_hubs_status    ON cb_hubs (status);
CREATE INDEX IF NOT EXISTS idx_cb_hubs_workspace ON cb_hubs (workspace_id);

-- Junction: hub ↔ content (user-managed links)
CREATE TABLE IF NOT EXISTS cb_hub_content (
    hub_id     UUID NOT NULL REFERENCES cb_hubs(hub_id) ON DELETE CASCADE,
    content_id TEXT NOT NULL,
    linked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (hub_id, content_id)
);

CREATE INDEX IF NOT EXISTS idx_cb_hub_content_cid ON cb_hub_content (content_id);
