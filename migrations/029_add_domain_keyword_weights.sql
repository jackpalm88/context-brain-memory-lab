-- Migration: Domain Keyword Weights — per-domain keyword scoring table
-- Phase: 7c  Owner: classify pipeline  Idempotent: safe to run multiple times.
-- Weight range: 0.0 (suppress) to 5.0 (strong signal), 1.0 = neutral.
-- UNIQUE uses COALESCE to treat NULL context_hint as '' for dedup (PostgreSQL functional index).

CREATE TABLE IF NOT EXISTS cb_domain_keyword_weights (
    weight_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id    UUID NOT NULL
                 REFERENCES cb_discovered_domains(domain_id) ON DELETE CASCADE,
    keyword      TEXT NOT NULL,
    weight       FLOAT NOT NULL DEFAULT 1.0
                 CHECK (weight BETWEEN 0.0 AND 5.0),
    context_hint TEXT,
    source       TEXT NOT NULL DEFAULT 'auto_classify'
                 CHECK (source IN ('auto_classify', 'manual', 'imported')),
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dedup: one weight per (domain, keyword, context_hint) — NULL context_hint treated as ''
CREATE UNIQUE INDEX IF NOT EXISTS idx_kwt_domain_keyword_ctx
    ON cb_domain_keyword_weights(domain_id, keyword, COALESCE(context_hint, ''));

-- Lookup by domain (most common access pattern)
CREATE INDEX IF NOT EXISTS idx_kwt_domain_id
    ON cb_domain_keyword_weights(domain_id);

-- Lookup by keyword (reverse: find all domains that weight a keyword)
CREATE INDEX IF NOT EXISTS idx_kwt_keyword
    ON cb_domain_keyword_weights(keyword);

-- Null-expiry weights (permanent/manual weights — excludes time-limited learned weights)
-- Time-bounded weights use expires_at IS NOT NULL; filtering by NOW() happens in query, not index.
CREATE INDEX IF NOT EXISTS idx_kwt_permanent
    ON cb_domain_keyword_weights(domain_id, keyword)
    WHERE expires_at IS NULL;
