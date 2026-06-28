"""Shared body/chunk persistence primitive (M10.1).

Single source of truth for writing a content body into ``content_chunks``
(chunk_index 0) plus optional, opt-in embedding. Cursor-agnostic so both
the ingest orchestrator (``ApiAdapter.create_content_minimal``, RealDictCursor
-> Mapping rows) and the round-trip primitive
(``PostgresPersistenceBackend.put_content_record``, plain cursor -> tuple rows)
can share it inside their own transactions. The caller owns the transaction
and the content_items row; this primitive only touches content_chunks.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from memory_lab.providers.embedding_backend import EmbeddingBackend, EmbeddingRequest


@dataclass
class ChunkWriteResult:
    chunk_written: bool = False
    chunk_id: Optional[str] = None
    word_count: int = 0
    uses_embeddings: bool = False
    uses_vector_db: bool = False
    warnings: Tuple[str, ...] = ()


def _first_value(row: Any) -> Any:
    """Extract the single RETURNING value cursor-agnostically.

    Plain cursors yield tuples (row[0]); RealDictCursor yields a Mapping.
    """
    if row is None:
        return None
    if isinstance(row, Mapping):
        return next(iter(row.values()))
    return row[0]


def persist_body_chunks(
    cur: Any,
    content_id: str,
    workspace_id: Optional[str],
    text: Optional[str],
    *,
    embedding_backend: Optional[EmbeddingBackend] = None,
    vector_enabled: bool = False,
) -> ChunkWriteResult:
    """Replace chunk_index 0 for ``content_id`` with ``text`` (idempotent).

    Runs inside the caller's transaction on the supplied cursor. Embedding is
    opt-in and best-effort: skipped entirely unless ``vector_enabled`` and a
    configured backend are provided. Never raises on a missing/disabled
    provider — the body text is always persisted regardless.
    """
    cur.execute(
        "DELETE FROM content_chunks WHERE content_id = %s::uuid AND chunk_index = 0",
        (content_id,),
    )
    if not text:
        return ChunkWriteResult(chunk_written=False)

    word_count = len(text.split())
    cur.execute(
        """
        INSERT INTO content_chunks (content_id, workspace_id, chunk_index, chunk_text, word_count)
        VALUES (%s::uuid, %s::uuid, 0, %s, %s)
        RETURNING chunk_id::text
        """,
        (content_id, workspace_id, text, word_count),
    )
    chunk_id = _first_value(cur.fetchone())

    embed_warning = _maybe_store_chunk_embedding(
        cur, chunk_id, text, embedding_backend=embedding_backend, vector_enabled=vector_enabled
    )
    uses_embeddings = embed_warning is None and vector_enabled
    # "provider_disabled" is an expected no-op, not a degradation worth surfacing.
    warnings: Tuple[str, ...] = (
        () if (embed_warning is None or embed_warning == "provider_disabled") else (embed_warning,)
    )
    return ChunkWriteResult(
        chunk_written=True,
        chunk_id=chunk_id,
        word_count=word_count,
        uses_embeddings=uses_embeddings,
        uses_vector_db=uses_embeddings,
        warnings=warnings,
    )


def _maybe_store_chunk_embedding(
    cur: Any,
    chunk_id: str,
    text: str,
    *,
    embedding_backend: Optional[EmbeddingBackend],
    vector_enabled: bool,
) -> Optional[str]:
    if not vector_enabled:
        return "provider_disabled"
    if embedding_backend is None or not embedding_backend.is_configured:
        return "provider_disabled"
    response = embedding_backend.embed_text(EmbeddingRequest(text=text))
    if not response.is_ok or response.dimensions != 1536:
        return response.failure_reason.value if response.failure_reason is not None else "embedding_degraded"
    cur.execute(
        """
        UPDATE content_chunks
           SET embedding = %s::vector,
               embedding_provider = %s,
               embedding_model = %s,
               embedding_dimensions = %s,
               embedded_at = NOW(),
               embedding_status = 'embedded',
               embedding_failure_reason = NULL
         WHERE chunk_id = %s::uuid
        """,
        (
            _vector_literal(response.vector),
            embedding_backend.provider_name,
            _embedding_model_label(embedding_backend),
            response.dimensions,
            chunk_id,
        ),
    )
    return None


def _vector_literal(vector) -> str:
    return "[" + ",".join(str(float(v)) for v in vector) + "]"


def _embedding_model_label(backend: EmbeddingBackend) -> str:
    getter = getattr(backend, "_get_model", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return backend.provider_name
    return backend.provider_name
