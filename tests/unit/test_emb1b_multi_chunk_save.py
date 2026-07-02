"""EMB-1B Acceptance Tests — Multi-Chunk Save.

Validates the EMB-1B contract:
  1. Short content (< DEFAULT_TARGET_CHUNK_CHARS) → 1 chunk persisted
  2. Long content (> DEFAULT_MAX_CHUNK_CHARS * 2) → N > 1 chunks persisted
  3. Embedding attempted per chunk when enabled, stored per chunk
  4. Embedding failure on one chunk does not prevent others from persisting
  5. persist_body_chunks remains unchanged (compatibility path)
  6. MultiChunkWriteResult carries correct chunk/embedding counts
  7. Deterministic: same content → same chunk count on repeated calls
  8. Empty content → 0 chunks, no exception

Design principle:
  Embedding generation is best-effort, never transactional.
  Chunking is provider-free (DeterministicContentChunker).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from memory_lab.ingestion.chunking import DEFAULT_MAX_CHUNK_CHARS, DeterministicContentChunker
from memory_lab.persistence.body_chunks import (
    ChunkWriteResult,
    MultiChunkWriteResult,
    persist_body_chunks,
    persist_multi_chunks,
)
from memory_lab.providers.embedding_backend import (
    EmbeddingBackend,
    EmbeddingBatchRequest,
    EmbeddingBatchResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CID = str(uuid.uuid4())
WS = str(uuid.uuid4())

SHORT_TEXT = "This is a short content item."
LONG_TEXT = "Word " * (DEFAULT_MAX_CHUNK_CHARS // 4)  # well above 2 chunks


@dataclass
class _FakeCursor:
    """Minimal cursor stub that records INSERTs and DELETEs."""

    rows_inserted: List[Dict[str, Any]] = field(default_factory=list)
    deletes: int = 0
    updates: int = 0
    _next_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def execute(self, sql: str, params: Any = None) -> None:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("DELETE"):
            self.deletes += 1
        elif sql_upper.startswith("INSERT"):
            self.rows_inserted.append({"sql": sql, "params": params})
        elif sql_upper.startswith("UPDATE"):
            self.updates += 1

    def fetchone(self) -> Tuple[str]:
        return (str(uuid.uuid4()),)


class _ConfiguredEmbeddingBackend(EmbeddingBackend):
    """Stub backend that always succeeds."""

    call_count: int = 0

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "stub_provider"

    @property
    def vector_dimensions(self) -> int:
        return 1536

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        _ConfiguredEmbeddingBackend.call_count += 1
        return EmbeddingResponse(vector=[0.1] * 1536, dimensions=1536)

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        vecs = [[0.1] * 1536 for _ in request.texts]
        return EmbeddingBatchResponse(vectors=vecs, dimensions=1536)

    @classmethod
    def reset(cls) -> None:
        cls.call_count = 0


class _FailingEmbeddingBackend(EmbeddingBackend):
    """Stub backend that always raises on embed_text."""

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "stub_failing"

    @property
    def vector_dimensions(self) -> int:
        return 1536

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise RuntimeError("simulated provider failure")

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        raise RuntimeError("simulated provider failure")


# ---------------------------------------------------------------------------
# persist_multi_chunks unit tests
# ---------------------------------------------------------------------------

class TestPersistMultiChunks:
    def test_single_chunk_written(self) -> None:
        cur = _FakeCursor()
        result = persist_multi_chunks(cur, CID, WS, [(0, SHORT_TEXT)])
        assert result.chunks_written == 1
        assert len(cur.rows_inserted) == 1
        assert cur.deletes == 1  # DELETE before INSERT

    def test_multi_chunk_written(self) -> None:
        cur = _FakeCursor()
        chunks = [(0, "first chunk text"), (1, "second chunk text"), (2, "third chunk text")]
        result = persist_multi_chunks(cur, CID, WS, chunks)
        assert result.chunks_written == 3
        assert len(cur.rows_inserted) == 3
        assert cur.deletes == 1

    def test_empty_chunks_no_exception(self) -> None:
        cur = _FakeCursor()
        result = persist_multi_chunks(cur, CID, WS, [])
        assert result.chunks_written == 0
        assert result.embeddings_attempted == 0
        assert len(cur.rows_inserted) == 0

    def test_embedding_attempted_per_chunk(self) -> None:
        _ConfiguredEmbeddingBackend.reset()
        cur = _FakeCursor()
        backend = _ConfiguredEmbeddingBackend()
        chunks = [(0, "alpha"), (1, "beta"), (2, "gamma")]
        result = persist_multi_chunks(
            cur, CID, WS, chunks,
            embedding_backend=backend,
            vector_enabled=True,
        )
        assert result.embeddings_attempted == 3
        assert result.embeddings_stored == 3
        assert _ConfiguredEmbeddingBackend.call_count == 3
        assert cur.updates == 3  # one UPDATE per chunk embedding

    def test_embedding_failure_best_effort_content_persists(self) -> None:
        cur = _FakeCursor()
        backend = _FailingEmbeddingBackend()
        chunks = [(0, "first"), (1, "second")]
        result = persist_multi_chunks(
            cur, CID, WS, chunks,
            embedding_backend=backend,
            vector_enabled=True,
        )
        # Content persisted despite embedding failure
        assert result.chunks_written == 2
        assert len(cur.rows_inserted) == 2
        # Embeddings attempted but not stored
        assert result.embeddings_attempted == 2
        assert result.embeddings_stored == 0
        # Warnings recorded
        assert len(result.warnings) == 2

    def test_no_embedding_when_disabled(self) -> None:
        _ConfiguredEmbeddingBackend.reset()
        cur = _FakeCursor()
        backend = _ConfiguredEmbeddingBackend()
        result = persist_multi_chunks(
            cur, CID, WS, [(0, SHORT_TEXT)],
            embedding_backend=backend,
            vector_enabled=False,
        )
        assert result.embeddings_attempted == 0
        assert _ConfiguredEmbeddingBackend.call_count == 0

    def test_no_embedding_when_backend_none(self) -> None:
        cur = _FakeCursor()
        result = persist_multi_chunks(
            cur, CID, WS, [(0, SHORT_TEXT)],
            embedding_backend=None,
            vector_enabled=True,  # enabled but no backend
        )
        assert result.embeddings_attempted == 0
        assert result.chunks_written == 1

    def test_result_type_is_multi_chunk_write_result(self) -> None:
        cur = _FakeCursor()
        result = persist_multi_chunks(cur, CID, WS, [(0, SHORT_TEXT)])
        assert isinstance(result, MultiChunkWriteResult)

    def test_idempotent_delete_before_insert(self) -> None:
        """DELETE fires once regardless of chunk count."""
        cur = _FakeCursor()
        chunks = [(i, f"chunk {i} text") for i in range(5)]
        persist_multi_chunks(cur, CID, WS, chunks)
        assert cur.deletes == 1
        assert len(cur.rows_inserted) == 5


# ---------------------------------------------------------------------------
# DeterministicContentChunker → persist_multi_chunks integration
# ---------------------------------------------------------------------------

class TestChunkerIntegration:
    def test_short_content_produces_one_chunk(self) -> None:
        chunker = DeterministicContentChunker()
        result = chunker.chunk_text(SHORT_TEXT)
        assert len(result.chunks) == 1
        chunks = [(c.index, c.text) for c in result.chunks]
        cur = _FakeCursor()
        mc_result = persist_multi_chunks(cur, CID, WS, chunks)
        assert mc_result.chunks_written == 1

    def test_long_content_produces_multiple_chunks(self) -> None:
        chunker = DeterministicContentChunker()
        result = chunker.chunk_text(LONG_TEXT)
        assert len(result.chunks) > 1, "long content must produce multiple chunks"
        chunks = [(c.index, c.text) for c in result.chunks]
        cur = _FakeCursor()
        mc_result = persist_multi_chunks(cur, CID, WS, chunks)
        assert mc_result.chunks_written == len(chunks)

    def test_deterministic_same_content_same_chunk_count(self) -> None:
        chunker = DeterministicContentChunker()
        r1 = chunker.chunk_text(LONG_TEXT)
        r2 = chunker.chunk_text(LONG_TEXT)
        assert len(r1.chunks) == len(r2.chunks)
        for c1, c2 in zip(r1.chunks, r2.chunks):
            assert c1.text == c2.text
            assert c1.index == c2.index

    def test_embedding_per_chunk_on_long_content(self) -> None:
        _ConfiguredEmbeddingBackend.reset()
        chunker = DeterministicContentChunker()
        chunking = chunker.chunk_text(LONG_TEXT)
        n = len(chunking.chunks)
        assert n > 1
        chunks = [(c.index, c.text) for c in chunking.chunks]
        cur = _FakeCursor()
        backend = _ConfiguredEmbeddingBackend()
        result = persist_multi_chunks(
            cur, CID, WS, chunks,
            embedding_backend=backend,
            vector_enabled=True,
        )
        assert result.embeddings_attempted == n
        assert result.embeddings_stored == n
        assert _ConfiguredEmbeddingBackend.call_count == n


# ---------------------------------------------------------------------------
# persist_body_chunks compatibility — must remain unchanged (EMB-1A path)
# ---------------------------------------------------------------------------

class TestPersistBodyChunksUnchanged:
    def test_returns_chunk_write_result(self) -> None:
        cur = _FakeCursor()
        result = persist_body_chunks(cur, CID, WS, SHORT_TEXT)
        assert isinstance(result, ChunkWriteResult)

    def test_short_text_chunk_written(self) -> None:
        cur = _FakeCursor()
        result = persist_body_chunks(cur, CID, WS, SHORT_TEXT)
        assert result.chunk_written is True
        assert len(cur.rows_inserted) == 1

    def test_empty_text_not_written(self) -> None:
        cur = _FakeCursor()
        result = persist_body_chunks(cur, CID, WS, "")
        assert result.chunk_written is False
        assert len(cur.rows_inserted) == 0

    def test_embedding_best_effort_on_failure(self) -> None:
        cur = _FakeCursor()
        backend = _FailingEmbeddingBackend()
        result = persist_body_chunks(
            cur, CID, WS, SHORT_TEXT,
            embedding_backend=backend,
            vector_enabled=True,
        )
        # Content persisted despite embedding failure
        assert result.chunk_written is True
        assert "embedding_exception" in result.warnings
