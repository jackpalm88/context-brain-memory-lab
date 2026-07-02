"""EMB-1C: Embedding Backfill Runner.

Fills missing embeddings on existing content_chunks rows using the current
multi-chunk semantics (EMB-1B).  Provider-free dry-run is always safe;
live execution requires a configured EmbeddingBackend.

Design principles:
  - Best-effort: a failure on one chunk is logged and skipped, not fatal.
  - Idempotent: re-running against already-embedded chunks is a no-op
    (SELECT only returns embedding_status IS NULL OR 'failed').
  - Workspace-scoped: pass workspace_id to limit blast radius.
  - Dry-run mode: counts eligible chunks and reports plan without writes.
  - Batch size + limit controls: safe for large corpora.

Usage (via scripts/embedding_backfill.py):
    python3 scripts/embedding_backfill.py --dsn "..." --dry-run
    python3 scripts/embedding_backfill.py --dsn "..." [--workspace-id UUID]
        [--batch-size 100] [--limit 1000]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, List, Optional, Sequence, Tuple

from memory_lab.persistence.body_chunks import _maybe_store_chunk_embedding
from memory_lab.providers.embedding_backend import EmbeddingBackend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ChunkBackfillResult:
    """Result for a single chunk backfill attempt."""
    chunk_id: str
    content_id: str
    skipped: bool = False        # dry-run or already embedded
    embedded: bool = False
    warning: Optional[str] = None


@dataclass
class BackfillStats:
    """Aggregate stats for a backfill run."""
    eligible: int = 0            # chunks needing embedding at scan time
    attempted: int = 0           # embed_text called
    stored: int = 0              # embedding written to DB
    skipped_dry_run: int = 0     # dry-run counted but not written
    failed: int = 0              # embed_text exception or degraded response
    warnings: Tuple[str, ...] = ()

    @property
    def success_rate(self) -> float:
        if self.attempted == 0:
            return 0.0
        return self.stored / self.attempted


@dataclass
class BackfillPlan:
    """Output of a dry-run scan — no writes performed."""
    eligible: int
    workspace_id: Optional[str]
    limit: Optional[int]
    batch_size: int
    sample_chunk_ids: Tuple[str, ...]   # first ≤10 chunk_ids for inspection
    note: str = "dry-run: no embeddings written"


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_SELECT_ELIGIBLE = """
    SELECT cc.chunk_id::text, cc.content_id::text, cc.chunk_text
      FROM content_chunks cc
     WHERE (cc.embedding_status IS NULL OR cc.embedding_status = 'failed')
       AND cc.chunk_text IS NOT NULL
       AND cc.chunk_text <> ''
       {workspace_clause}
     ORDER BY cc.content_id, cc.chunk_index
     {limit_clause}
"""


def _build_select(
    workspace_id: Optional[str],
    limit: Optional[int],
) -> Tuple[str, List[Any]]:
    ws_clause = "AND cc.workspace_id = %s::uuid" if workspace_id else ""
    lim_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = _SELECT_ELIGIBLE.format(
        workspace_clause=ws_clause,
        limit_clause=lim_clause,
    )
    params: List[Any] = [workspace_id] if workspace_id else []
    return sql, params


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class EmbeddingBackfillRunner:
    """Backfill missing embeddings on content_chunks.

    Args:
        conn_factory: callable() -> psycopg2-compatible connection.
            Injected so the runner is fully hermetic in tests.
        embedding_backend: configured EmbeddingBackend; None = dry-run only.
        workspace_id: optional UUID string to scope the run.
        batch_size: commit every N chunks during live execution.
        limit: max chunks to process per run (None = no limit).
    """

    def __init__(
        self,
        conn_factory: Callable[[], Any],
        embedding_backend: Optional[EmbeddingBackend] = None,
        *,
        workspace_id: Optional[str] = None,
        batch_size: int = 100,
        limit: Optional[int] = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._backend = embedding_backend
        self._workspace_id = workspace_id
        self._batch_size = max(1, batch_size)
        self._limit = limit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dry_run(self) -> BackfillPlan:
        """Scan eligible chunks and return a plan without writing anything."""
        sql, params = _build_select(self._workspace_id, self._limit)
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        chunk_ids = tuple(r[0] for r in rows[:10])
        return BackfillPlan(
            eligible=len(rows),
            workspace_id=self._workspace_id,
            limit=self._limit,
            batch_size=self._batch_size,
            sample_chunk_ids=chunk_ids,
        )

    def execute(self) -> BackfillStats:
        """Live backfill — embed and store.  Best-effort per chunk."""
        if self._backend is None or not self._backend.is_configured:
            logger.warning("[backfill] no configured backend — nothing to do")
            return BackfillStats()

        sql, params = _build_select(self._workspace_id, self._limit)
        conn = self._conn_factory()
        stats = BackfillStats()
        all_warnings: List[str] = []

        try:
            with conn.cursor() as scan_cur:
                scan_cur.execute(sql, params)
                rows = scan_cur.fetchall()

            stats.eligible = len(rows)
            batch: List[Tuple[str, str, str]] = []

            for row in rows:
                chunk_id, content_id, chunk_text = row[0], row[1], row[2]
                batch.append((chunk_id, content_id, chunk_text))
                if len(batch) >= self._batch_size:
                    b_stats, b_warnings = self._process_batch(conn, batch)
                    stats.attempted += b_stats[0]
                    stats.stored += b_stats[1]
                    stats.failed += b_stats[2]
                    all_warnings.extend(b_warnings)
                    batch = []

            if batch:
                b_stats, b_warnings = self._process_batch(conn, batch)
                stats.attempted += b_stats[0]
                stats.stored += b_stats[1]
                stats.failed += b_stats[2]
                all_warnings.extend(b_warnings)

        finally:
            conn.close()

        stats.warnings = tuple(all_warnings)
        return stats

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_batch(
        self,
        conn: Any,
        batch: List[Tuple[str, str, str]],
    ) -> Tuple[Tuple[int, int, int], List[str]]:
        """Process one batch; commit at end. Returns (attempted, stored, failed), warnings."""
        attempted = stored = failed = 0
        warnings: List[str] = []

        with conn.cursor() as cur:
            for chunk_id, content_id, chunk_text in batch:
                attempted += 1
                warning = _maybe_store_chunk_embedding(
                    cur,
                    chunk_id,
                    chunk_text,
                    embedding_backend=self._backend,
                    vector_enabled=True,
                )
                if warning is None:
                    stored += 1
                    logger.debug("[backfill] embedded chunk %s (content %s)", chunk_id, content_id)
                elif warning == "provider_disabled":
                    # backend became unconfigured mid-run — treat as failure
                    failed += 1
                    warnings.append(f"chunk {chunk_id[:8]}: provider_disabled mid-run")
                else:
                    failed += 1
                    warnings.append(f"chunk {chunk_id[:8]}: {warning}")
                    logger.warning("[backfill] chunk %s failed: %s", chunk_id, warning)

            conn.commit()

        return (attempted, stored, failed), warnings
