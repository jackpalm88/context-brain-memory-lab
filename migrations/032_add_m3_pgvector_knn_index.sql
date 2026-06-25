-- 032_add_m3_pgvector_knn_index.sql
-- M3: opt-in pgvector retrieval/write seam support.
-- Scope: additive vector index and embedding metadata only.
-- Historical migrations 000..031 are intentionally untouched.

ALTER TABLE content_chunks
    ADD COLUMN IF NOT EXISTS embedding_provider TEXT,
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER,
    ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS embedding_status TEXT,
    ADD COLUMN IF NOT EXISTS embedding_failure_reason TEXT;

DO $$
BEGIN
    -- Empty-env/M2 DB gates may intentionally strip pgvector. Keep this migration
    -- additive and safe there; real M3 pgvector tests run with the vector type.
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        ALTER TABLE content_chunks
            ADD COLUMN IF NOT EXISTS embedding vector(1536);

        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_ivfflat
        ON content_chunks
        USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
        WHERE embedding IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_chunks_workspace_embedding_ready
        ON content_chunks(workspace_id, embedded_at DESC)
        WHERE embedding IS NOT NULL;
    END IF;
END $$;
