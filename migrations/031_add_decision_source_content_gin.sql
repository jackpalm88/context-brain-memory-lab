-- Migration: CF-002 Stage 1 — index the decision↔content join
-- Idempotent: safe to run multiple times.
-- Serves the public decisions-by-content read (GET /decisions/by-content/{content_id})
-- AND the pre-existing internal cleanup deletion guard, which scanned
-- source_content_ids unindexed (memory_lab/api/routers/cleanup.py).

CREATE INDEX IF NOT EXISTS idx_decision_nodes_source_content_gin
    ON cb_decision_nodes USING GIN (source_content_ids)
    WHERE source_content_ids IS NOT NULL;

-- Reverse lookup on the (currently vestigial, Stage-2-activated) canonical link.
CREATE INDEX IF NOT EXISTS idx_decision_nodes_content_id
    ON cb_decision_nodes(content_id)
    WHERE content_id IS NOT NULL;
