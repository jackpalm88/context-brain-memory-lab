-- Migration 004: Alias layer for semantic term normalization
-- Provides controlled synonym resolution before graph BFS expansion

CREATE TABLE IF NOT EXISTS cb_aliases (
    id          SERIAL PRIMARY KEY,
    term        TEXT NOT NULL,
    canonical   TEXT NOT NULL,
    confidence  FLOAT NOT NULL DEFAULT 0.9
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status      TEXT NOT NULL DEFAULT 'approved'
                    CHECK (status IN ('approved', 'pending', 'rejected')),
    source      TEXT NOT NULL DEFAULT 'manual',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS cb_aliases_term_canonical_idx
    ON cb_aliases (LOWER(term), LOWER(canonical));

CREATE INDEX IF NOT EXISTS cb_aliases_term_idx
    ON cb_aliases (LOWER(term));

CREATE INDEX IF NOT EXISTS cb_aliases_canonical_idx
    ON cb_aliases (LOWER(canonical));

-- Candidate pairs produced by batch scoring job (Phase 2)
CREATE TABLE IF NOT EXISTS cb_alias_candidates (
    id          SERIAL PRIMARY KEY,
    term_a      TEXT NOT NULL,
    term_b      TEXT NOT NULL,
    score       FLOAT,
    source      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS cb_alias_candidates_pair_idx
    ON cb_alias_candidates (LOWER(term_a), LOWER(term_b));
