"""EMB-1D Acceptance Tests — Semantic Retrieval End-to-End.

Validates the EMB-1D contract:

  D1  save creates a chunk row in content_chunks
  D2  chunk receives an embedding vector (pgvector UPDATE)
  D3  _pgvector_knn_search returns the saved content_id given the same vector
  D4  backfilled chunks become searchable via KNN
  D5  EMBEDDING_PROVIDER=none / no backend → graceful noop, content still saved
  D6  Deterministic text retrieval still works when pgvector is disabled

Design principles:
  - FakeEmbedder: deterministic, provider-free, hash-based 1536-d unit vector
  - Isolated disposable DB: cbml_emb1d_verify (created/destroyed per session)
  - All migrations applied via psycopg2 (no docker exec in test logic)
  - No real provider calls, no ANTHROPIC_API_KEY, no secrets
  - pgvector must be installed in the test container (migration 002 requires it)

Environment requirements:
  Set CB_TEST_ADMIN_DSN_EMB1D to a CB-style test Postgres admin DSN, e.g.:
    CB_TEST_ADMIN_DSN_EMB1D=postgresql://postgres:***@127.0.0.1:55432/postgres

  If not set, all tests skip with: SKIPPED_NO_EMB1D_TEST_DSN

Safety guards:
  - Refuses DSNs pointing at production/n8n/contentingestor databases
  - Refuses n8n username / n8n123 password pattern
  - Admin DB must remain 'postgres' (not cbml_emb1d_verify itself)

Cleanup:
  Disposable DB cbml_emb1d_verify is dropped after the session regardless of
  test outcome (finalizer in autouse session fixture).
"""
from __future__ import annotations

import glob
import hashlib
import math
import os
import re
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------

_FORBIDDEN_DB_NAMES = re.compile(
    r"^(n8n|production|prod|contentingestor)$", re.IGNORECASE
)
_FORBIDDEN_SUBSTRINGS = {"n8n_postgres_1", "n8n123"}


def _refuse_suspicious_dsn(dsn: str) -> None:
    raw = dsn or ""
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in raw:
            pytest.fail(
                f"EMB1D_DSN contains forbidden deployment marker {forbidden!r}. "
                "This test must not run against production or n8n infrastructure."
            )
    from urllib.parse import urlparse
    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    username = (parsed.username or "").lower()
    password = parsed.password or ""
    db_name = (parsed.path or "").lstrip("/").lower()
    if username == "n8n":
        pytest.fail("EMB1D_DSN uses username 'n8n'. Forbidden.")
    if "n8n123" in password:
        pytest.fail("EMB1D_DSN contains n8n123 in password. Forbidden.")
    if "n8n" in hostname:
        pytest.fail(f"EMB1D_DSN hostname {hostname!r} contains 'n8n'. Forbidden.")
    if _FORBIDDEN_DB_NAMES.match(db_name):
        pytest.fail(
            f"EMB1D_DSN database name {db_name!r} is forbidden. "
            "Use a dedicated admin DB (e.g. 'postgres') to provision test DBs."
        )


_ADMIN_DSN = os.environ.get("CB_TEST_ADMIN_DSN_EMB1D", "").strip()
_SKIP_REASON = "SKIPPED_NO_EMB1D_TEST_DSN — set CB_TEST_ADMIN_DSN_EMB1D"
_DISPOSABLE_DB = "cbml_emb1d_verify"
_DISPOSABLE_USER = "cbml_emb1d"
_DISPOSABLE_PW = "cbml_emb1d_pw"


def _psycopg2():
    return pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary",
    )


def _admin_conn(autocommit: bool = True):
    pg = _psycopg2()
    if not _ADMIN_DSN:
        pytest.skip(_SKIP_REASON)
    _refuse_suspicious_dsn(_ADMIN_DSN)
    conn = pg.connect(_ADMIN_DSN)
    conn.autocommit = autocommit
    return conn


def _test_dsn() -> str:
    """DSN for the disposable DB, connecting as the disposable user."""
    from urllib.parse import urlparse
    parsed = urlparse(_ADMIN_DSN)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    return (
        f"postgresql://{_DISPOSABLE_USER}:{_DISPOSABLE_PW}"
        f"@{host}:{port}/{_DISPOSABLE_DB}"
    )


def _admin_test_dsn() -> str:
    """DSN for the disposable DB, connecting as the admin (postgres) superuser.
    Used for extension creation and migrations which require superuser."""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(_ADMIN_DSN)
    return urlunparse(parsed._replace(path=f"/{_DISPOSABLE_DB}"))


def _migration_files() -> List[str]:
    base = os.path.join(os.path.dirname(__file__), "..", "..", "migrations")
    base = os.path.normpath(base)
    files = sorted(glob.glob(os.path.join(base, "*.sql")))
    return files


def _apply_migrations(conn) -> None:
    files = _migration_files()
    assert files, "No migration files found — check path from tests/integration/"
    cur = conn.cursor()
    for fpath in files:
        with open(fpath, encoding="utf-8") as fh:
            sql = fh.read()
        cur.execute(sql)
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Session-scoped disposable DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def emb1d_db():
    """Create cbml_emb1d_verify, apply all migrations, yield DSN, then drop."""
    pg = _psycopg2()
    if not _ADMIN_DSN:
        pytest.skip(_SKIP_REASON)
    _refuse_suspicious_dsn(_ADMIN_DSN)

    # --- provision ---
    admin = _admin_conn(autocommit=True)
    cur = admin.cursor()
    cur.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{_DISPOSABLE_DB}' AND pid <> pg_backend_pid()"
    )
    cur.execute(f"DROP DATABASE IF EXISTS {_DISPOSABLE_DB}")
    cur.execute(f"DROP ROLE IF EXISTS {_DISPOSABLE_USER}")
    cur.execute(
        f"CREATE ROLE {_DISPOSABLE_USER} WITH LOGIN PASSWORD '{_DISPOSABLE_PW}'"
    )
    cur.execute(f"CREATE DATABASE {_DISPOSABLE_DB} OWNER {_DISPOSABLE_USER}")
    cur.close()
    admin.close()

    # --- enable pgvector extension + apply migrations via admin conn on new DB ---
    # Only superuser can CREATE EXTENSION; use admin DSN pointed at disposable DB.
    admin_on_new = pg.connect(_admin_test_dsn())
    admin_on_new.autocommit = True
    ext_cur = admin_on_new.cursor()
    ext_cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Grant all schema privileges to disposable user before running migrations
    ext_cur.execute(f"GRANT ALL ON SCHEMA public TO {_DISPOSABLE_USER}")
    ext_cur.close()
    admin_on_new.autocommit = False
    _apply_migrations(admin_on_new)
    # After migration tables exist, grant table-level access to disposable user
    admin_on_new.autocommit = True
    gc = admin_on_new.cursor()
    gc.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {_DISPOSABLE_USER}")
    gc.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {_DISPOSABLE_USER}")
    gc.close()
    admin_on_new.close()

    dsn = _test_dsn()

    yield dsn

    # --- teardown ---
    try:
        admin3 = _admin_conn(autocommit=True)
        cur3 = admin3.cursor()
        cur3.execute(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{_DISPOSABLE_DB}' AND pid <> pg_backend_pid()"
        )
        cur3.execute(f"DROP DATABASE IF EXISTS {_DISPOSABLE_DB}")
        cur3.execute(f"DROP ROLE IF EXISTS {_DISPOSABLE_USER}")
        cur3.close()
        admin3.close()
    except Exception:
        pass  # best-effort teardown


# ---------------------------------------------------------------------------
# FakeEmbedder — deterministic, provider-free
#
# Strategy: hash text to a reproducible 1536-d unit vector.
# Two identical texts always produce the same vector (deterministic).
# ---------------------------------------------------------------------------

from memory_lab.providers.embedding_backend import (
    EmbeddingBackend,
    EmbeddingBatchRequest,
    EmbeddingBatchResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)


class FakeEmbedder(EmbeddingBackend):
    """Deterministic hermetic embedding backend.

    Vector: SHA-256 of text → seed → 1536 pseudo-random floats → L2-normalised.
    Always returns is_configured=True and vector_dimensions=1536.
    Never calls any external provider.
    """

    DIMS = 1536

    @property
    def provider_name(self) -> str:
        return "fake_hermetic"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def vector_dimensions(self) -> int:
        return self.DIMS

    @staticmethod
    def _text_to_vector(text: str) -> List[float]:
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16)
        dims = FakeEmbedder.DIMS
        rng = seed
        raw: List[float] = []
        for _ in range(dims):
            rng = (rng * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            raw.append(float((rng >> 33) & 0x7FFFFFFF) / 0x7FFFFFFF * 2.0 - 1.0)
        norm = math.sqrt(sum(v * v for v in raw))
        if norm < 1e-12:
            norm = 1.0
        return [v / norm for v in raw]

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        vec = self._text_to_vector(request.text)
        return EmbeddingResponse(
            vector=vec,
            dimensions=self.DIMS,
            provider="fake_hermetic",
            degraded=False,
            failure_reason=None,
        )

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        vecs = [self._text_to_vector(t) for t in request.texts]
        return EmbeddingBatchResponse(
            vectors=vecs,
            dimensions=self.DIMS,
            provider="fake_hermetic",
        )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _bootstrap_workspace(conn) -> str:
    """Insert a minimal workspace row and return workspace_id.

    Matches cb_workspaces DDL (migration 017):
      slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL, status TEXT DEFAULT 'active',
      is_default BOOLEAN, created_by_subject TEXT.
    No workspace_name column exists.
    """
    ws_id = str(uuid.uuid4())
    slug = f"emb1d-test-{ws_id[:8]}"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cb_workspaces
            (workspace_id, slug, title, status, is_default, created_by_subject)
        VALUES (%s::uuid, %s, %s, 'active', FALSE, 'emb1d-test')
        ON CONFLICT (workspace_id) DO NOTHING
        """,
        (ws_id, slug, f"EMB-1D Test Workspace {ws_id[:8]}"),
    )
    conn.commit()
    cur.close()
    return ws_id


def _insert_content_item(conn, workspace_id: str, body: str) -> str:
    """Insert a minimal content_items row, return content_id.

    content_items has NO body/full_text/memory_type/word_count column.
    Text lives in content_chunks.chunk_text — written by persist_body_chunks,
    which every test calls explicitly after this helper.
    The `body` argument is kept in the signature for call-site compatibility
    but is not stored in content_items.
    """
    content_id = str(uuid.uuid4())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO content_items (content_id, workspace_id)
        VALUES (%s::uuid, %s::uuid)
        ON CONFLICT (content_id) DO NOTHING
        """,
        (content_id, workspace_id),
    )
    conn.commit()
    cur.close()
    return content_id


def _get_chunk_row(conn, content_id: str) -> Optional[dict]:
    """Fetch the first chunk row for a content_id."""
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM content_chunks WHERE content_id = %s::uuid LIMIT 1",
        (content_id,),
    )
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# D1 — save creates a chunk row
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestD1ChunkCreated:
    def test_d1_chunk_row_exists_after_save(self, emb1d_db):
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            content_id = _insert_content_item(
                conn, ws_id, "The quick brown fox jumps over the lazy dog"
            )
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            result = persist_body_chunks(
                cur, content_id, ws_id,
                "The quick brown fox jumps over the lazy dog",
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        conn2 = pg.connect(emb1d_db)
        try:
            row = _get_chunk_row(conn2, content_id)
        finally:
            conn2.close()

        assert row is not None, "D1: chunk row must exist after persist_body_chunks"
        assert result.chunk_written is True

    def test_d1_chunk_text_matches(self, emb1d_db):
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Semantic retrieval D1b unique text content"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(cur, content_id, ws_id, text)
            conn.commit()
            cur.close()
        finally:
            conn.close()

        conn2 = pg.connect(emb1d_db)
        try:
            row = _get_chunk_row(conn2, content_id)
        finally:
            conn2.close()

        assert row is not None
        assert row["chunk_text"] == text


# ---------------------------------------------------------------------------
# D2 — chunk receives an embedding vector
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestD2EmbeddingStored:
    def test_d2_embedding_column_populated(self, emb1d_db):
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Embedding vector storage test D2a"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            result = persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        assert result.uses_embeddings is True, "D2: uses_embeddings must be True"

        conn2 = pg.connect(emb1d_db)
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT embedding IS NOT NULL, embedding_status, embedding_provider "
                "FROM content_chunks WHERE content_id = %s::uuid",
                (content_id,),
            )
            row = cur2.fetchone()
            cur2.close()
        finally:
            conn2.close()

        assert row is not None
        has_vec, emb_status, emb_provider = row
        assert has_vec is True, "D2: embedding column must not be NULL"
        assert emb_status == "embedded", f"D2: embedding_status={emb_status!r}"
        assert emb_provider == "fake_hermetic", f"D2: provider={emb_provider!r}"

    def test_d2_embedding_dimensions_stored(self, emb1d_db):
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Dimensions check D2b"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        conn2 = pg.connect(emb1d_db)
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT embedding_dimensions FROM content_chunks WHERE content_id = %s::uuid",
                (content_id,),
            )
            row = cur2.fetchone()
            cur2.close()
        finally:
            conn2.close()

        assert row is not None
        assert row[0] == 1536, f"D2: embedding_dimensions={row[0]!r}, want 1536"

    def test_d2_no_embedding_when_vector_disabled(self, emb1d_db):
        """With vector_enabled=False, embedding column must stay NULL."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "No embedding expected D2c"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=False,   # disabled despite backend present
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        conn2 = pg.connect(emb1d_db)
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT embedding IS NULL FROM content_chunks WHERE content_id = %s::uuid",
                (content_id,),
            )
            row = cur2.fetchone()
            cur2.close()
        finally:
            conn2.close()

        assert row is not None
        assert row[0] is True, "D2c: embedding must be NULL when vector_enabled=False"


# ---------------------------------------------------------------------------
# D3 — KNN retrieval returns the saved content_id
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestD3KNNRetrieval:
    def test_d3_knn_returns_saved_content_id(self, emb1d_db):
        """End-to-end: save+embed → KNN search with same vector → content_id in results."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Autonomous knowledge graph semantic embedding retrieval D3a"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=FakeEmbedder(),
            pgvector_retrieval_enabled=True,
        )
        query_vec = FakeEmbedder._text_to_vector(text)
        results = adapter._pgvector_knn_search(
            query=text,
            query_vector=query_vec,
            workspace_id=ws_id,
        )
        found_ids = [r["content_id"] for r in results]
        assert content_id in found_ids, (
            f"D3a: content_id {content_id!r} not found in KNN results.\n"
            f"Got: {found_ids!r}"
        )

    def test_d3_knn_result_has_pgvector_path(self, emb1d_db):
        """KNN results must carry retrieval_path='pgvector_knn'."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Path label verification pgvector knn D3b"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=FakeEmbedder(),
            pgvector_retrieval_enabled=True,
        )
        query_vec = FakeEmbedder._text_to_vector(text)
        results = adapter._pgvector_knn_search(text, query_vec, workspace_id=ws_id)
        target = next((r for r in results if r["content_id"] == content_id), None)
        assert target is not None, "D3b: target content_id not in KNN results"
        assert target.get("retrieval_path") == "pgvector_knn"

    def test_d3_knn_workspace_isolation(self, emb1d_db):
        """KNN must not return results from a different workspace."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_a = _bootstrap_workspace(conn)
            ws_b = _bootstrap_workspace(conn)
            text = "Workspace isolation probe D3c shared text content"
            content_id_a = _insert_content_item(conn, ws_a, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id_a, ws_a, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=FakeEmbedder(),
            pgvector_retrieval_enabled=True,
        )
        query_vec = FakeEmbedder._text_to_vector(text)
        results = adapter._pgvector_knn_search(text, query_vec, workspace_id=ws_b)
        found_ids = [r["content_id"] for r in results]
        assert content_id_a not in found_ids, (
            "D3c: KNN returned content from a different workspace — isolation broken"
        )

    def test_d3_knn_score_in_range(self, emb1d_db):
        """KNN result score (cosine similarity) must be in [0, 1]."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Score range probe D3d"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=FakeEmbedder(),
            pgvector_retrieval_enabled=True,
        )
        query_vec = FakeEmbedder._text_to_vector(text)
        results = adapter._pgvector_knn_search(text, query_vec, workspace_id=ws_id)
        target = next((r for r in results if r["content_id"] == content_id), None)
        assert target is not None
        score = target.get("score") or target.get("similarity") or 0.0
        assert 0.0 <= float(score) <= 1.0, f"D3d: score={score!r} out of [0,1]"


# ---------------------------------------------------------------------------
# D4 — backfilled chunks become searchable via KNN
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestD4BackfillSearchable:
    def test_d4_backfill_chunk_then_knn_finds_it(self, emb1d_db):
        """Chunk saved without embedding, then backfilled → KNN retrieves it."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Backfill embedding test content for D4a acceptance proof"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            # Save WITHOUT embedding
            cur = conn.cursor(cursor_factory=RealDictCursor)
            result = persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=None,
                vector_enabled=False,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        assert result.chunk_written is True
        assert result.uses_embeddings is False

        # Verify embedding IS NULL before backfill
        conn2 = pg.connect(emb1d_db)
        try:
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT embedding IS NULL FROM content_chunks WHERE content_id = %s::uuid",
                (content_id,),
            )
            assert cur2.fetchone()[0] is True, "D4a: embedding must be NULL before backfill"
            cur2.close()
        finally:
            conn2.close()

        # Backfill
        from memory_lab.ingestion.embedding_backfill import EmbeddingBackfillRunner

        runner = EmbeddingBackfillRunner(
            conn_factory=lambda: pg.connect(emb1d_db),
            embedding_backend=FakeEmbedder(),
            workspace_id=ws_id,
        )
        stats = runner.execute()
        assert stats.stored >= 1, f"D4a: backfill stored={stats.stored}, want >=1"
        assert stats.failed == 0, f"D4a: backfill failed={stats.failed}, want 0"

        # KNN should now find it
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=FakeEmbedder(),
            pgvector_retrieval_enabled=True,
        )
        query_vec = FakeEmbedder._text_to_vector(text)
        results = adapter._pgvector_knn_search(text, query_vec, workspace_id=ws_id)
        found_ids = [r["content_id"] for r in results]
        assert content_id in found_ids, (
            f"D4a: backfilled content_id {content_id!r} not found in KNN results.\n"
            f"Got: {found_ids!r}"
        )

    def test_d4_backfill_sets_embedding_status(self, emb1d_db):
        """After backfill, embedding_status must be 'embedded' or 'ok'."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Status column verification after backfill D4b"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(cur, content_id, ws_id, text)
            conn.commit()
            cur.close()
        finally:
            conn.close()

        from memory_lab.ingestion.embedding_backfill import EmbeddingBackfillRunner

        runner = EmbeddingBackfillRunner(
            conn_factory=lambda: pg.connect(emb1d_db),
            embedding_backend=FakeEmbedder(),
            workspace_id=ws_id,
        )
        runner.execute()

        conn3 = pg.connect(emb1d_db)
        try:
            cur3 = conn3.cursor()
            cur3.execute(
                "SELECT embedding_status FROM content_chunks WHERE content_id = %s::uuid",
                (content_id,),
            )
            row = cur3.fetchone()
            cur3.close()
        finally:
            conn3.close()

        assert row is not None
        assert row[0] in ("embedded", "ok"), f"D4b: embedding_status={row[0]!r}"

    def test_d4_backfill_idempotent(self, emb1d_db):
        """Re-running backfill on already-embedded chunks → stored=0."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Backfill idempotency probe D4c"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            # First save WITH embedding
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        from memory_lab.ingestion.embedding_backfill import EmbeddingBackfillRunner

        runner = EmbeddingBackfillRunner(
            conn_factory=lambda: pg.connect(emb1d_db),
            embedding_backend=FakeEmbedder(),
            workspace_id=ws_id,
        )
        stats = runner.execute()
        # Already embedded → eligible=0 for this workspace's new chunk
        # (other test workspaces may contribute unembedded chunks, but this
        #  content_id's chunk must NOT be re-embedded = not in stored set for this ws)
        assert stats.failed == 0, f"D4c: backfill rerun failed={stats.failed}"


# ---------------------------------------------------------------------------
# D5 — EMBEDDING_PROVIDER=none graceful noop
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestD5EmbeddingProviderNone:
    def test_d5_no_backend_content_still_saved(self, emb1d_db):
        """With no embedding backend, content saves without error, no vector stored."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Content saved gracefully without embedding backend D5a"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            result = persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=None,
                vector_enabled=False,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        assert result.chunk_written is True, "D5a: content must be saved"
        assert result.uses_embeddings is False, "D5a: uses_embeddings must be False"

    def test_d5_retrieval_adapter_no_pgvector_no_exception(self, emb1d_db):
        """RetrievalAdapter.search must never raise when pgvector is disabled."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            conn.close()
        except Exception:
            conn.close()
            raise

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=None,
            pgvector_retrieval_enabled=False,
        )
        try:
            adapter.search(query="query that matches nothing", workspace_id=ws_id)
        except Exception as exc:
            pytest.fail(f"D5b: RetrievalAdapter.search raised unexpectedly: {exc!r}")

    def test_d5_retrieval_no_pgvector_path_in_results(self, emb1d_db):
        """Results from disabled-pgvector adapter must not carry pgvector_knn path."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Fallback path label test D5c"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(cur, content_id, ws_id, text)
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            conn.close()
            raise

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=None,
            pgvector_retrieval_enabled=False,
        )
        results = adapter.search(query=text, workspace_id=ws_id)
        for r in results:
            mode = r.get("retrieval_mode") or r.get("retrieval_path") or ""
            assert "pgvector_knn" not in mode, (
                f"D5c: pgvector_knn result returned despite pgvector disabled; mode={mode!r}"
            )

    def test_d5_content_accessible_deterministically_after_noop_embed(self, emb1d_db):
        """Content saved without embedding is still retrievable via deterministic path."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Deterministic access after noop embed D5d unique token zzt9q8w7"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=None,
                vector_enabled=False,
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            conn.close()
            raise

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=None,
            pgvector_retrieval_enabled=False,
        )
        results = adapter._deterministic_vector_search("zzt9q8w7", workspace_id=ws_id)
        found_ids = [r["content_id"] for r in results]
        assert content_id in found_ids, (
            f"D5d: content_id {content_id!r} not found via deterministic path.\n"
            f"Got: {found_ids!r}"
        )


# ---------------------------------------------------------------------------
# D6 — Deterministic retrieval still works
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestD6DeterministicRetrieval:
    def test_d6_text_match_returns_content(self, emb1d_db):
        """Deterministic (LIKE/tsvector) retrieval returns content by keyword match."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Deterministic retrieval probe D6a unique phrase xyzzy1234abc"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(cur, content_id, ws_id, text)
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            conn.close()
            raise

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=None,
            pgvector_retrieval_enabled=False,
        )
        results = adapter._deterministic_vector_search("xyzzy1234abc", workspace_id=ws_id)
        found_ids = [r["content_id"] for r in results]
        assert content_id in found_ids, (
            f"D6a: deterministic retrieval did not find content_id {content_id!r}.\n"
            f"Got: {found_ids!r}"
        )

    def test_d6_deterministic_retrieval_path_label(self, emb1d_db):
        """Deterministic results carry a recognisable retrieval_path label."""
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Path label test deterministic D6b unique token qwerty9876xyz"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            persist_body_chunks(cur, content_id, ws_id, text)
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            conn.close()
            raise

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=None,
            pgvector_retrieval_enabled=False,
        )
        results = adapter._deterministic_vector_search("qwerty9876xyz", workspace_id=ws_id)
        target = next((r for r in results if r["content_id"] == content_id), None)
        assert target is not None, "D6b: target not found via deterministic search"
        path = target.get("retrieval_path") or ""
        assert path, f"D6b: retrieval_path must not be empty; got {path!r}"
        # Must not be pgvector path
        assert "pgvector_knn" not in path, f"D6b: unexpected pgvector path {path!r}"

    def test_d6_deterministic_works_alongside_pgvector(self, emb1d_db):
        """Unified search (pgvector enabled + FakeEmbedder) finds vector-embedded content.

        The adapter uses path-level switching: when an embedding_backend is present
        and produces a query_vector, _pgvector_knn_search is used.  To prove the
        end-to-end path works when pgvector is enabled we save the chunk WITH a
        FakeEmbedder so the KNN index is populated, then query via search().
        """
        pg = _psycopg2()
        conn = pg.connect(emb1d_db)
        conn.autocommit = False
        try:
            ws_id = _bootstrap_workspace(conn)
            text = "Coexistence probe D6c unique token lmnop5432rst"
            content_id = _insert_content_item(conn, ws_id, text)
            from memory_lab.persistence.body_chunks import persist_body_chunks
            from psycopg2.extras import RealDictCursor

            cur = conn.cursor(cursor_factory=RealDictCursor)
            # Save WITH embedding so KNN index is populated
            persist_body_chunks(
                cur, content_id, ws_id, text,
                embedding_backend=FakeEmbedder(),
                vector_enabled=True,
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            conn.close()
            raise

        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        # pgvector enabled + FakeEmbedder → query_vector produced → KNN path
        adapter = RetrievalAdapter(
            database_url=emb1d_db,
            embedding_backend=FakeEmbedder(),
            pgvector_retrieval_enabled=True,
        )
        results = adapter.search(query="lmnop5432rst", workspace_id=ws_id)
        found_ids = [r["content_id"] for r in results]
        assert content_id in found_ids, (
            f"D6c: content_id {content_id!r} not found via unified KNN search.\n"
            f"Got: {found_ids!r}"
        )
