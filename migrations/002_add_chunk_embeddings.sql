ALTER TABLE content_chunks
ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Optional but useful for later: mark missing embeddings fast
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_null
ON content_chunks(content_id)
WHERE embedding IS NULL;
