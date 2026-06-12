-- Migration: Classify Pipeline — classification history + content_items classify columns
-- Phase: 7a  Owner: classify pipeline  Idempotent: safe to run multiple times.
-- INVARIANT: classify pipeline NEVER writes is_current or current_state_scope (migration 030).
-- NOTE: is_active_classification here != is_current on content_items (different systems, different semantics).

CREATE TABLE IF NOT EXISTS cb_classification_history (
    classify_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id             UUID NOT NULL,
    content_id               UUID REFERENCES content_items(content_id) ON DELETE SET NULL,
    memory_type              TEXT NOT NULL
                             CHECK (memory_type IN (
                                 'milestone', 'decision', 'principle', 'anchor',
                                 'evidence', 'plan_roadmap', 'raw_memory')),
    memory_sub_type          TEXT,
    classify_confidence      FLOAT
                             CHECK (classify_confidence BETWEEN 0.0 AND 1.0),
    classifier_version       TEXT NOT NULL DEFAULT 'heuristic_v1',
    project_topic            TEXT,
    classification_signals   JSONB DEFAULT '{}',
    is_active_classification BOOLEAN NOT NULL DEFAULT TRUE,
    classified_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Active classifications per workspace + type (hot path for retrieval filter)
CREATE INDEX IF NOT EXISTS idx_classify_workspace_type_active
    ON cb_classification_history(workspace_id, memory_type)
    WHERE is_active_classification = TRUE;

-- Reverse lookup: content_id → full classification history
CREATE INDEX IF NOT EXISTS idx_classify_content_id
    ON cb_classification_history(content_id, classified_at DESC);

-- Project-topic scoped active classifications (conflict detection seed)
CREATE INDEX IF NOT EXISTS idx_classify_project_topic_active
    ON cb_classification_history(workspace_id, memory_type, project_topic)
    WHERE is_active_classification = TRUE AND project_topic IS NOT NULL;

-- Denormalized classify columns on content_items (hot retrieval path — avoids JOIN)
ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS memory_type         TEXT
        CHECK (memory_type IN (
            'milestone', 'decision', 'principle', 'anchor',
            'evidence', 'plan_roadmap', 'raw_memory')),
    ADD COLUMN IF NOT EXISTS memory_sub_type     TEXT,
    ADD COLUMN IF NOT EXISTS classify_confidence FLOAT
        CHECK (classify_confidence BETWEEN 0.0 AND 1.0),
    ADD COLUMN IF NOT EXISTS classified_at       TIMESTAMPTZ;

-- Filter by memory_type in retrieval (hot path)
CREATE INDEX IF NOT EXISTS idx_content_memory_type
    ON content_items(memory_type)
    WHERE memory_type IS NOT NULL;

-- Catch-up job anchor: unclassified content awaiting classify pipeline
CREATE INDEX IF NOT EXISTS idx_content_unclassified
    ON content_items(created_at DESC)
    WHERE memory_type IS NULL;
