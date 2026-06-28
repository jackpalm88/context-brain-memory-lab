"""M10.2 — content-level hash deduplication (deterministic, no DB).

create_content_minimal computes a SHA-256 content_hash and, before scoring,
looks up an existing persisted row scoped by (workspace_id, content_hash).
On a hit it is a PURE READ: returns the existing content_id with
duplicate=True and performs no writes (no INSERT/UPDATE, no content_chunks,
no classify, no current-state resolver). New content carries content_hash on
its INSERT and writes its body as in M10.1.
"""
import hashlib

import pytest
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-0000000000a1"
EXISTING = "00000000-0000-0000-0000-0000000000e1"
NEW = "00000000-0000-0000-0000-0000000000d2"


class FakeCursor:
    def __init__(self, fetch_queue=None, fetch=None):
        self.executed = []
        self._queue = list(fetch_queue) if fetch_queue is not None else None
        self._fetch = fetch

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self._queue is not None:
            return self._queue.pop(0) if self._queue else None
        return self._fetch


class FakeConn:
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


def _sql(cur):
    return " || ".join(s for s, _ in cur.executed)


def _make_adapter():
    from memory_lab.api.services.api_adapter import ApiAdapter
    return ApiAdapter("postgresql://fake/fake")


def _persist_event():
    ev = MagicMock()
    ev.scores.composite = 0.9
    ev.scores.quality = 0.9
    ev.scores.relevance = 0.9
    ev.scores.novelty = 0.9
    ev.circuit_open = False
    ev.fallback_reason = ""
    return ev


# ---- hash util ----

def test_compute_content_hash_deterministic():
    from memory_lab.api.utils.content_signatures import compute_content_hash
    h1 = compute_content_hash("alpha beta")
    assert h1 == compute_content_hash("alpha beta")
    assert h1 == hashlib.sha256("alpha beta".encode("utf-8")).hexdigest()
    assert len(h1) == 64


def test_compute_content_hash_none_is_empty():
    from memory_lab.api.utils.content_signatures import compute_content_hash
    assert compute_content_hash(None) == hashlib.sha256(b"").hexdigest()


# ---- lookup scope ----

def test_find_duplicate_lookup_workspace_scoped():
    adapter = _make_adapter()
    cur = FakeCursor(fetch={"content_id": EXISTING})
    with patch.object(adapter, "_conn", lambda: FakeConn(cur)):
        out = adapter._find_duplicate_content_id("hash123", WS)
    sql = _sql(cur)
    assert "content_items" in sql
    assert "content_hash" in sql
    assert "IS NOT DISTINCT FROM" in sql
    assert out == EXISTING


def test_find_duplicate_null_workspace():
    adapter = _make_adapter()
    cur = FakeCursor(fetch={"content_id": EXISTING})
    with patch.object(adapter, "_conn", lambda: FakeConn(cur)):
        out = adapter._find_duplicate_content_id("hash123", None)
    assert out == EXISTING


def test_find_duplicate_none_when_absent():
    adapter = _make_adapter()
    cur = FakeCursor(fetch=None)
    with patch.object(adapter, "_conn", lambda: FakeConn(cur)):
        assert adapter._find_duplicate_content_id("hash123", WS) is None


# ---- duplicate branch is a pure read ----

def test_duplicate_branch_pure_read_returns_existing():
    adapter = _make_adapter()
    cur = FakeCursor(fetch={"content_id": EXISTING})
    with patch.object(adapter, "_conn", lambda: FakeConn(cur)), \
         patch("memory_lab.api.services.api_adapter.score_content") as mock_score, \
         patch("memory_lab.api.services.api_adapter.tier_route") as mock_tier, \
         patch.object(adapter, "_run_classify_and_write") as mock_classify, \
         patch("memory_lab.api.services.api_adapter.persist_body_chunks") as mock_body, \
         patch("memory_lab.api.services.api_adapter.resolve_current_state_after_ingest") as mock_resolver:
        resp = adapter.create_content_minimal(content="dup text", workspace_id=WS, created_by_subject=None)

    raw = _sql(cur)
    upper = raw.upper()
    assert "SELECT" in upper
    assert "INSERT" not in upper
    assert "UPDATE" not in upper
    assert "content_chunks" not in raw
    mock_score.assert_not_called()
    mock_tier.assert_not_called()
    mock_classify.assert_not_called()
    mock_body.assert_not_called()
    mock_resolver.assert_not_called()

    assert resp["content_id"] == EXISTING
    assert resp["duplicate"] is True
    assert resp["created"] is False
    assert resp["persisted"] is True
    assert resp["discarded"] is False
    assert resp["mode"] == "deduplicated"


# ---- new content carries content_hash + writes body + duplicate False ----

def test_non_duplicate_insert_carries_content_hash_and_writes_body():
    from memory_lab.governance.tier_router import TierDecision
    adapter = _make_adapter()
    cur = FakeCursor(fetch_queue=[{"content_id": NEW}, ("chunk-uuid",)])
    tier = TierDecision(tier="persistent", reason="ok", rule_id="T", should_persist=True)
    with patch.object(adapter, "_conn", lambda: FakeConn(cur)), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=_persist_event()), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=tier), \
         patch.object(adapter, "_run_classify_and_write", return_value={}):
        resp = adapter.create_content_minimal(content="brand new content", workspace_id=WS)

    sql = _sql(cur)
    assert "INSERT INTO content_items" in sql
    assert "content_hash" in sql
    assert "INSERT INTO content_chunks" in sql
    assert resp["created"] is True
    assert resp["duplicate"] is False
