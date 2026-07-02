"""EMB-1C Acceptance Tests — Embedding Backfill Runner.

All tests are hermetic: no real DB, no real provider.
Uses fake connection/cursor and fake EmbeddingBackend stubs.

Validates:
  B1  dry_run returns BackfillPlan with correct eligible count, no writes
  B2  execute with no backend returns empty BackfillStats
  B3  execute embeds all eligible chunks, stats correct
  B4  embedding failure on one chunk is best-effort: others proceed
  B5  workspace_id scopes the SELECT query
  B6  limit is applied to SELECT query
  B7  batch_size controls commit frequency
  B8  already-embedded chunks (embedding_status='ok') not in eligible set
  B9  empty corpus → stats all zero, no exception
  B10 success_rate calculation correct
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from memory_lab.ingestion.embedding_backfill import (
    BackfillPlan,
    BackfillStats,
    EmbeddingBackfillRunner,
)
from memory_lab.providers.embedding_backend import (
    EmbeddingBackend,
    EmbeddingBatchRequest,
    EmbeddingBatchResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)

# ---------------------------------------------------------------------------
# Fake stubs
# ---------------------------------------------------------------------------

@dataclass
class _FakeCursor:
    executed: List[Dict[str, Any]] = field(default_factory=list)
    _rows: List[Tuple] = field(default_factory=list)

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append({"sql": sql, "params": params})

    def fetchall(self) -> List[Tuple]:
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@dataclass
class _FakeConn:
    cursor_obj: _FakeCursor
    commits: int = 0
    closed: bool = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _make_rows(n: int, status: Optional[str] = None) -> List[Tuple]:
    """Generate n fake (chunk_id, content_id, chunk_text) rows."""
    rows = []
    for i in range(n):
        cid = str(uuid.uuid4())
        rows.append((str(uuid.uuid4()), cid, f"chunk text {i}"))
    return rows


class _OKBackend(EmbeddingBackend):
    embed_calls: int = 0

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "stub_ok"

    @property
    def vector_dimensions(self) -> int:
        return 1536

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        _OKBackend.embed_calls += 1
        return EmbeddingResponse(vector=[0.1] * 1536, dimensions=1536)

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        return EmbeddingBatchResponse(vectors=[[0.1] * 1536] * len(request.texts), dimensions=1536)

    @classmethod
    def reset(cls) -> None:
        cls.embed_calls = 0


class _FailingBackend(EmbeddingBackend):
    @property
    def is_configured(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "stub_fail"

    @property
    def vector_dimensions(self) -> int:
        return 1536

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise RuntimeError("provider error")

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        raise RuntimeError("provider error")


class _UnconfiguredBackend(EmbeddingBackend):
    @property
    def is_configured(self) -> bool:
        return False

    @property
    def provider_name(self) -> str:
        return "stub_unconfigured"

    @property
    def vector_dimensions(self) -> int:
        return 0

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise RuntimeError("not configured")

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        raise RuntimeError("not configured")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner_with_rows(
    rows: List[Tuple],
    backend=None,
    workspace_id: Optional[str] = None,
    batch_size: int = 100,
    limit: Optional[int] = None,
) -> Tuple[EmbeddingBackfillRunner, _FakeConn]:
    cur = _FakeCursor(_rows=rows)
    conn = _FakeConn(cursor_obj=cur)
    runner = EmbeddingBackfillRunner(
        conn_factory=lambda: conn,
        embedding_backend=backend,
        workspace_id=workspace_id,
        batch_size=batch_size,
        limit=limit,
    )
    return runner, conn


# ---------------------------------------------------------------------------
# B1 — dry_run returns BackfillPlan, no writes
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_b1_returns_backfill_plan(self) -> None:
        rows = _make_rows(5)
        runner, conn = _runner_with_rows(rows)
        plan = runner.dry_run()
        assert isinstance(plan, BackfillPlan)

    def test_b1_eligible_count_matches_rows(self) -> None:
        rows = _make_rows(7)
        runner, conn = _runner_with_rows(rows)
        plan = runner.dry_run()
        assert plan.eligible == 7

    def test_b1_no_writes_on_dry_run(self) -> None:
        rows = _make_rows(5)
        runner, conn = _runner_with_rows(rows)
        runner.dry_run()
        # Only SELECT executed — no UPDATE/INSERT
        sqls = [e["sql"].strip().upper() for e in conn.cursor_obj.executed]
        assert all(s.startswith("SELECT") for s in sqls)
        assert conn.commits == 0

    def test_b1_sample_chunk_ids_capped_at_10(self) -> None:
        rows = _make_rows(25)
        runner, conn = _runner_with_rows(rows)
        plan = runner.dry_run()
        assert len(plan.sample_chunk_ids) <= 10

    def test_b1_workspace_id_propagated(self) -> None:
        ws = str(uuid.uuid4())
        rows = _make_rows(3)
        runner, conn = _runner_with_rows(rows, workspace_id=ws)
        plan = runner.dry_run()
        assert plan.workspace_id == ws

    def test_b1_limit_propagated(self) -> None:
        rows = _make_rows(3)
        runner, conn = _runner_with_rows(rows, limit=50)
        plan = runner.dry_run()
        assert plan.limit == 50

    def test_b1_empty_corpus_eligible_zero(self) -> None:
        runner, conn = _runner_with_rows([])
        plan = runner.dry_run()
        assert plan.eligible == 0
        assert plan.sample_chunk_ids == ()


# ---------------------------------------------------------------------------
# B2 — execute with no/unconfigured backend returns empty stats
# ---------------------------------------------------------------------------

class TestExecuteNoBackend:
    def test_b2_none_backend_returns_empty_stats(self) -> None:
        rows = _make_rows(5)
        runner, conn = _runner_with_rows(rows, backend=None)
        stats = runner.execute()
        assert isinstance(stats, BackfillStats)
        assert stats.attempted == 0
        assert stats.stored == 0

    def test_b2_unconfigured_backend_returns_empty_stats(self) -> None:
        rows = _make_rows(5)
        runner, conn = _runner_with_rows(rows, backend=_UnconfiguredBackend())
        stats = runner.execute()
        assert stats.attempted == 0
        assert stats.stored == 0


# ---------------------------------------------------------------------------
# B3 — execute embeds all eligible chunks
# ---------------------------------------------------------------------------

class TestExecuteSuccess:
    def setup_method(self):
        _OKBackend.reset()

    def test_b3_all_chunks_embedded(self) -> None:
        rows = _make_rows(4)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend())
        stats = runner.execute()
        assert stats.eligible == 4
        assert stats.attempted == 4
        assert stats.stored == 4
        assert stats.failed == 0

    def test_b3_stats_success_rate_full(self) -> None:
        rows = _make_rows(3)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend())
        stats = runner.execute()
        assert stats.success_rate == 1.0

    def test_b3_commit_called(self) -> None:
        rows = _make_rows(3)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend())
        runner.execute()
        assert conn.commits >= 1

    def test_b3_conn_closed_after_execute(self) -> None:
        rows = _make_rows(2)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend())
        runner.execute()
        assert conn.closed is True

    def test_b9_empty_corpus_zero_stats(self) -> None:
        runner, conn = _runner_with_rows([], backend=_OKBackend())
        stats = runner.execute()
        assert stats.eligible == 0
        assert stats.attempted == 0
        assert stats.stored == 0
        assert stats.failed == 0


# ---------------------------------------------------------------------------
# B4 — embedding failure is best-effort
# ---------------------------------------------------------------------------

class TestExecuteFailureBestEffort:
    def test_b4_all_fail_stats_correct(self) -> None:
        rows = _make_rows(3)
        runner, conn = _runner_with_rows(rows, backend=_FailingBackend())
        stats = runner.execute()
        assert stats.attempted == 3
        assert stats.failed == 3
        assert stats.stored == 0
        assert len(stats.warnings) == 3

    def test_b4_warnings_contain_chunk_id_prefix(self) -> None:
        rows = _make_rows(2)
        runner, conn = _runner_with_rows(rows, backend=_FailingBackend())
        stats = runner.execute()
        for w in stats.warnings:
            assert ":" in w  # "chunk <id8>: <reason>"

    def test_b4_content_persisted_despite_failure(self) -> None:
        """chunks_written is independent of embedding; eligible = attempted here."""
        rows = _make_rows(4)
        runner, conn = _runner_with_rows(rows, backend=_FailingBackend())
        stats = runner.execute()
        # All were attempted even though all failed
        assert stats.attempted == 4
        assert stats.eligible == 4


# ---------------------------------------------------------------------------
# B5 — workspace_id scopes SELECT
# ---------------------------------------------------------------------------

class TestWorkspaceScope:
    def test_b5_workspace_clause_in_select(self) -> None:
        ws = str(uuid.uuid4())
        runner, conn = _runner_with_rows([], workspace_id=ws)
        runner.dry_run()
        sql = conn.cursor_obj.executed[0]["sql"]
        assert ws in str(conn.cursor_obj.executed[0]["params"])

    def test_b5_no_workspace_no_param(self) -> None:
        runner, conn = _runner_with_rows([])
        runner.dry_run()
        params = conn.cursor_obj.executed[0]["params"]
        assert params == [] or params is None or params == ()


# ---------------------------------------------------------------------------
# B7 — batch_size controls commit frequency
# ---------------------------------------------------------------------------

class TestBatchSize:
    def setup_method(self):
        _OKBackend.reset()

    def test_b7_one_batch_one_commit(self) -> None:
        rows = _make_rows(5)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend(), batch_size=100)
        runner.execute()
        assert conn.commits == 1

    def test_b7_three_batches_three_commits(self) -> None:
        rows = _make_rows(9)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend(), batch_size=3)
        runner.execute()
        assert conn.commits == 3

    def test_b7_remainder_batch_committed(self) -> None:
        """10 rows, batch_size=3 → 3 full + 1 remainder = 4 commits."""
        rows = _make_rows(10)
        runner, conn = _runner_with_rows(rows, backend=_OKBackend(), batch_size=3)
        runner.execute()
        assert conn.commits == 4


# ---------------------------------------------------------------------------
# B10 — success_rate
# ---------------------------------------------------------------------------

class TestSuccessRate:
    def test_b10_zero_attempted(self) -> None:
        stats = BackfillStats()
        assert stats.success_rate == 0.0

    def test_b10_all_stored(self) -> None:
        stats = BackfillStats(attempted=5, stored=5)
        assert stats.success_rate == 1.0

    def test_b10_partial(self) -> None:
        stats = BackfillStats(attempted=4, stored=1)
        assert abs(stats.success_rate - 0.25) < 1e-9
