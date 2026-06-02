-- ============================================================================
-- Migration: Add content_chunks table for Agentic RAG
-- Phase: 1 (Chunking Infrastructure)
-- Date: 2025-01-19
-- ============================================================================
-- 
-- PURPOSE:
-- Enable chunk-level storage for fine-grained semantic search.
-- This is prerequisite for:
--   - expand_context functionality
--   - chunk-level embeddings (Phase 2)
--   - coarse→fine search (Phase 3)
--
-- PLATFORM NORMATIVE:
-- - No domain-specific columns
-- - Deterministic chunking (same input → same output)
-- - Backward compatible (existing search still works)
--
-- ============================================================================

-- Create content_chunks table
CREATE TABLE IF NOT EXISTS content_chunks (
    -- Primary key
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key to parent content
    content_id UUID NOT NULL REFERENCES content_items(content_id) ON DELETE CASCADE,
    
    -- Chunk position within document
    chunk_index INTEGER NOT NULL,
    
    -- Chunk content
    chunk_text TEXT NOT NULL,
    word_count INTEGER,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint: one chunk per index per document
    UNIQUE(content_id, chunk_index)
);

-- Index for fast lookup by content_id
CREATE INDEX IF NOT EXISTS idx_chunks_content_id 
ON content_chunks(content_id);

-- Index for ordering within document
CREATE INDEX IF NOT EXISTS idx_chunks_content_index 
ON content_chunks(content_id, chunk_index);

-- ============================================================================
-- NOTE: Embedding column and vector index will be added in Phase 2
-- ============================================================================
-- 
-- Phase 2 will add:
--   ALTER TABLE content_chunks ADD COLUMN embedding vector(1536);
--   CREATE INDEX idx_chunks_embedding ON content_chunks 
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--
-- ============================================================================

COMMENT ON TABLE content_chunks IS 'Chunked content for fine-grained semantic search (Phase 1 Agentic RAG)';
COMMENT ON COLUMN content_chunks.chunk_index IS 'Zero-based position of chunk within parent document';
COMMENT ON COLUMN content_chunks.chunk_text IS 'Paragraph-based chunk text, typically 300-600 words';
