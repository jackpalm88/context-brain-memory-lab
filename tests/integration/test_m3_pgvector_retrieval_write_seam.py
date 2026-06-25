import glob
import os
import uuid
from pathlib import Path

import pytest

from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend
from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.providers.embedding_backend import EmbeddingBackend, EmbeddingBatchRequest, EmbeddingBatchResponse, EmbeddingRequest, EmbeddingResponse


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_db,
    pytest.mark.skipped_without_env,
]

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_DSN = (os.environ.get("CB_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
_SKIP_REASON = "CB_TEST_DATABASE_URL/DATABASE_URL not set; M3 pgvector integration is opt-in."


def _psycopg2():
    return pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary to run DB integration tests.",
    )


def _apply_migrations(dsn: str) -> None:
    psycopg2 = _psycopg2()
    conn = psycopg2.connect(dsn)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        for mig_path in sorted(glob.glob(str(_MIGRATIONS_DIR / "*.sql"))):
            sql = Path(mig_path).read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
    finally:
        conn.close()


@pytest.fixture(scope="session")
def pgvector_dsn():
    if not _DSN:
        pytest.skip(_SKIP_REASON)
    try:
        _apply_migrations(_DSN)
    except Exception as exc:
        pytest.skip(f"SKIPPED_POSTGRES_M3_PGVECTOR_DSN_UNUSABLE — could not apply migrations/connect: {exc}")
    return _DSN


class StubEmbeddingBackend(EmbeddingBackend):
    provider_name = "stub-m3"
    vector_dimensions = 1536
    is_configured = True

    def _vector_for(self, text: str) -> list[float]:
        lower = text.lower()
        if "far" in lower:
            return [0.0, 1.0] + [0.0] * 1534
        return [1.0, 0.0] + [0.0] * 1534

    def embed_text(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(vector=self._vector_for(request.text), dimensions=1536, provider=self.provider_name)

    def embed_batch(self, request: EmbeddingBatchRequest) -> EmbeddingBatchResponse:
        return EmbeddingBatchResponse(vectors=[self._vector_for(t) for t in request.texts], dimensions=1536, provider=self.provider_name)


class DisabledEmbeddingBackend(StubEmbeddingBackend):
    is_configured = False


def _record(workspace_id: str, text: str) -> ContentPersistenceRecord:
    return ContentPersistenceRecord(
        content_id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        text=text,
        title=text[:50],
        metadata={"milestone": "M3", "test": "pgvector"},
    )


def _force_chunk_created_at(dsn: str, content_id: str, timestamp: str) -> None:
    psycopg2 = _psycopg2()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE content_chunks SET created_at = %s::timestamptz WHERE content_id = %s::uuid", (timestamp, content_id))
        conn.commit()
    finally:
        conn.close()


def test_m3_db_no_key_falls_back_explicitly(pgvector_dsn):
    workspace_id = str(uuid.uuid4())
    backend = PostgresPersistenceBackend(pgvector_dsn, embedding_backend=DisabledEmbeddingBackend(), vector_embeddings_enabled=False)
    saved = backend.put_content_record(_record(workspace_id, "sharedtoken deterministic fallback close item"))
    assert saved.ok is True
    assert saved.metadata.uses_embeddings is False
    assert saved.metadata.uses_vector_db is False

    adapter = RetrievalAdapter(pgvector_dsn, embedding_backend=DisabledEmbeddingBackend(), pgvector_retrieval_enabled=True)
    results = adapter.search("sharedtoken", workspace_id=workspace_id, graph_boost=0.0)
    assert results
    assert results[0]["retrieval_mode"] == "deterministic_fallback"
    assert results[0]["embedding_status"] == "provider_disabled"


def test_m3_pgvector_stub_ranks_by_similarity_not_recency(pgvector_dsn):
    workspace_id = str(uuid.uuid4())
    backend = PostgresPersistenceBackend(pgvector_dsn, embedding_backend=StubEmbeddingBackend(), vector_embeddings_enabled=True)

    older_close = _record(workspace_id, "sharedtoken close semantic item")
    newer_far = _record(workspace_id, "sharedtoken far recency item")
    saved_close = backend.put_content_record(older_close)
    saved_far = backend.put_content_record(newer_far)
    assert saved_close.ok is True
    assert saved_far.ok is True
    assert saved_close.metadata.uses_embeddings is True
    assert saved_close.metadata.uses_vector_db is True

    _force_chunk_created_at(pgvector_dsn, older_close.content_id, "2026-01-01T00:00:00Z")
    _force_chunk_created_at(pgvector_dsn, newer_far.content_id, "2026-01-02T00:00:00Z")

    deterministic = RetrievalAdapter(pgvector_dsn, pgvector_retrieval_enabled=False).search("sharedtoken", workspace_id=workspace_id, graph_boost=0.0)
    assert deterministic[0]["content_id"] == newer_far.content_id
    assert deterministic[0]["retrieval_mode"] == "deterministic_fallback"

    vector_results = RetrievalAdapter(pgvector_dsn, embedding_backend=StubEmbeddingBackend(), pgvector_retrieval_enabled=True).search(
        "sharedtoken close query", workspace_id=workspace_id, graph_boost=0.0
    )
    assert vector_results[0]["content_id"] == older_close.content_id
    assert vector_results[0]["retrieval_mode"] == "pgvector_knn"
    assert vector_results[0]["retrieval_path"] == "pgvector_knn"
    assert vector_results[0]["embedding_status"] == "ok"
