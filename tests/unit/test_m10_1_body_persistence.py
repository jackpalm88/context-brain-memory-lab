"""M10.1 — shared body/chunk persistence primitive (deterministic, no DB).

persist_body_chunks is the single source of truth for writing a content body
into content_chunks (chunk_index 0) + optional opt-in embedding. It must be
cursor-agnostic so both the ingest orchestrator (ApiAdapter.create_content_minimal,
RealDictCursor -> dict rows) and the round-trip primitive
(PostgresPersistenceBackend.put_content_record, plain cursor -> tuple rows)
can share it inside their own transactions.
"""
import pytest
from unittest.mock import patch

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000001"
CID = "00000000-0000-0000-0000-000000000002"


class FakeCursor:
    """Records executed SQL; returns a preset row from fetchone()."""

    def __init__(self, fetch=None):
        self.executed = []
        self._fetch = fetch

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetch


def _sql(cur):
    return " || ".join(s for s, _ in cur.executed)


# ---------------------------------------------------------------------------
# Shared primitive — cursor agnostic
# ---------------------------------------------------------------------------

def test_persist_body_chunks_inserts_chunk_with_word_count_tuple_cursor():
    from memory_lab.persistence.body_chunks import persist_body_chunks
    cur = FakeCursor(fetch=("chunk-uuid",))  # plain cursor -> tuple row
    res = persist_body_chunks(cur, CID, WS, "alpha beta gamma")
    assert "INSERT INTO content_chunks" in _sql(cur)
    assert res.chunk_written is True
    assert res.chunk_id == "chunk-uuid"
    assert res.word_count == 3


def test_persist_body_chunks_cursor_agnostic_dict_cursor():
    """RealDictCursor returns a Mapping; chunk_id must still be extracted."""
    from memory_lab.persistence.body_chunks import persist_body_chunks
    cur = FakeCursor(fetch={"chunk_id": "chunk-uuid"})  # dict row
    res = persist_body_chunks(cur, CID, WS, "one two")
    assert res.chunk_id == "chunk-uuid"
    assert res.word_count == 2


def test_persist_body_chunks_empty_text_writes_no_chunk():
    from memory_lab.persistence.body_chunks import persist_body_chunks
    cur = FakeCursor()
    res = persist_body_chunks(cur, CID, WS, "")
    assert "INSERT INTO content_chunks" not in _sql(cur)
    assert res.chunk_written is False
    # idempotent replace: chunk_index 0 still cleared
    assert "DELETE FROM content_chunks" in _sql(cur)


def test_persist_body_chunks_replaces_chunk_index_zero():
    from memory_lab.persistence.body_chunks import persist_body_chunks
    cur = FakeCursor(fetch=("c",))
    persist_body_chunks(cur, CID, WS, "body")
    sql = _sql(cur)
    assert "DELETE FROM content_chunks" in sql
    assert sql.index("DELETE FROM content_chunks") < sql.index("INSERT INTO content_chunks")


def test_persist_body_chunks_embedding_off_by_default():
    from memory_lab.persistence.body_chunks import persist_body_chunks
    cur = FakeCursor(fetch=("c",))
    res = persist_body_chunks(cur, CID, WS, "body text")
    assert "embedding" not in _sql(cur).lower()
    assert res.uses_embeddings is False
    assert "provider_disabled" not in res.warnings


def test_persist_body_chunks_embedding_opt_in_fake_backend():
    from memory_lab.persistence.body_chunks import persist_body_chunks
    from memory_lab.providers.fake import FakeEmbeddingBackend
    backend = FakeEmbeddingBackend(dimensions=1536, preset_vector=[0.0] * 1536)
    cur = FakeCursor(fetch=("chunk-uuid",))
    res = persist_body_chunks(cur, CID, WS, "embed me", embedding_backend=backend, vector_enabled=True)
    sql = _sql(cur)
    assert "UPDATE content_chunks" in sql and "embedding" in sql.lower()
    assert res.uses_embeddings is True


# ---------------------------------------------------------------------------
# Wiring — create_content_minimal persists the submitted body
# ---------------------------------------------------------------------------

def _make_adapter():
    from memory_lab.api.services.api_adapter import ApiAdapter
    return ApiAdapter("postgresql://fake/fake")


class WiringConn:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        pass


class WiringCursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return {"content_id": CID}


def _persist_event():
    from unittest.mock import MagicMock
    ev = MagicMock()
    ev.scores.composite = 0.9
    ev.scores.quality = 0.9
    ev.scores.relevance = 0.9
    ev.scores.novelty = 0.9
    ev.circuit_open = False
    ev.fallback_reason = ""
    return ev


def test_create_content_persists_body_chunk():
    from memory_lab.governance.tier_router import TierDecision
    adapter = _make_adapter()
    cur = WiringCursor()
    tier = TierDecision(tier="persistent", reason="ok", rule_id="T", should_persist=True)
    with patch.object(adapter, "_conn", lambda: WiringConn(cur)), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=_persist_event()), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=tier), \
         patch.object(adapter, "_run_classify_and_write", return_value={}), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None):
        resp = adapter.create_content_minimal(content="hello world body", workspace_id=WS, created_by_subject=None)
    sql = " || ".join(s for s, _ in cur.executed)
    assert "INSERT INTO content_chunks" in sql
    assert resp["created"] is True


def test_discard_path_writes_no_body_chunk():
    from memory_lab.governance.tier_router import TierDecision
    adapter = _make_adapter()
    cur = WiringCursor()
    tier = TierDecision(tier="discard", reason="x", rule_id="X", should_persist=False)
    with patch.object(adapter, "_conn", lambda: WiringConn(cur)), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=_persist_event()), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=tier), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None):
        resp = adapter.create_content_minimal(content="discard me", workspace_id=WS)
    sql = " || ".join(s for s, _ in cur.executed)
    assert "content_chunks" not in sql
    assert resp["discarded"] is True
