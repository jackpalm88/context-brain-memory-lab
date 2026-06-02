-- Migration: Add graph layer for query expansion
-- Phase: Graph-Assisted Retrieval MVP

CREATE TABLE IF NOT EXISTS cb_edges (
    id          SERIAL PRIMARY KEY,
    from_node   TEXT NOT NULL,
    relation    TEXT NOT NULL,
    to_node     TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    confidence  FLOAT DEFAULT 0.9 CHECK (confidence >= 0 AND confidence <= 1),
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(from_node, relation, to_node, source_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON cb_edges(from_node);
CREATE INDEX IF NOT EXISTS idx_edges_to ON cb_edges(to_node);
CREATE INDEX IF NOT EXISTS idx_edges_confidence ON cb_edges(confidence);
CREATE INDEX IF NOT EXISTS idx_edges_source ON cb_edges(source_id);

CREATE TABLE IF NOT EXISTS cb_relation_types (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    weight      FLOAT DEFAULT 1.0,
    is_active   BOOLEAN DEFAULT TRUE
);

INSERT INTO cb_relation_types (name, description, weight) VALUES
('powers',      'A powers/enables B',       1.0),
('built_on',    'A is built on top of B',   1.0),
('replaced_by', 'A is replaced by B',       0.9),
('guides',      'A guides/helps B',          0.9),
('uses',        'A uses B',                  0.8),
('improves',    'A improves B',              0.8),
('related_to',  'Generic relation',          0.5)
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS cb_query_log (
    id               SERIAL PRIMARY KEY,
    original_query   TEXT NOT NULL,
    expanded_terms   TEXT[],
    results_count    INTEGER,
    used_graph       BOOLEAN DEFAULT FALSE,
    response_time_ms INTEGER,
    created_at       TIMESTAMP DEFAULT NOW()
);
