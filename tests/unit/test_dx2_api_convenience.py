"""
DX-2 unit tests — batch endpoint, similar endpoint, feedback endpoint.

Hermetic: all DB and adapter calls are mocked. No live DB, no live provider.
Covers the HTTP contract (status codes, response shape, summary counters,
error handling) — not the underlying retrieval algorithm.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
import memory_lab.api.routers.batch as batch_router
import memory_lab.api.routers.similar as similar_router
import memory_lab.api.routers.feedback as feedback_router

_FAKE_SETTINGS = SimpleNamespace(
    database_url="postgresql://unit:test@localhost/testdb",
    provider_embeddings_enabled=False,
)

_MOCK_AUTH = AuthContext(
    auth_subject_id="00000000-0000-0000-0000-000000000001",
    subject_type="user",
    workspace_id="00000000-0000-0000-0000-000000000002",
    role="owner",
    auth_method="api_key",
)


import memory_lab.api.dependencies.auth as _auth_mod
import memory_lab.api.workspace_context as _ws_mod
from memory_lab.api.workspace_context import WorkspaceContext

_FAKE_WORKSPACE = WorkspaceContext(
    workspace_id="00000000-0000-0000-0000-000000000002",
    source="db_default",
    is_default=True,
    local_dev_default_used=False,
    slug="unit-test",
)

def _permissive(*args, **kwargs):
    return _MOCK_AUTH


def _patch_auth(monkeypatch):
    """Patch workspace resolution so no DB call is made during auth."""
    monkeypatch.setattr(_ws_mod, "resolve_workspace_context", lambda *a, **kw: _FAKE_WORKSPACE)
    monkeypatch.setattr(_auth_mod, "resolve_workspace_context", lambda *a, **kw: _FAKE_WORKSPACE)
    monkeypatch.setattr(_auth_mod, "resolve_auth_context", lambda perm, ws, authz: _MOCK_AUTH)


# ---------------------------------------------------------------------------
# App factories — settings patched at module level, auth bypassed
# ---------------------------------------------------------------------------

def _batch_app(monkeypatch):
    _patch_auth(monkeypatch)
    monkeypatch.setattr(batch_router, "get_settings", lambda: _FAKE_SETTINGS)
    from memory_lab.api.routers.batch import router
    app = FastAPI()
    app.include_router(router)
    return app


def _similar_app(monkeypatch):
    _patch_auth(monkeypatch)
    monkeypatch.setattr(similar_router, "get_settings", lambda: _FAKE_SETTINGS)
    from memory_lab.api.routers.similar import router
    app = FastAPI()
    app.include_router(router)
    return app


def _feedback_app(monkeypatch):
    _patch_auth(monkeypatch)
    monkeypatch.setattr(feedback_router, "get_settings", lambda: _FAKE_SETTINGS)
    from memory_lab.api.routers.feedback import router
    app = FastAPI()
    app.include_router(router)
    return app


# ===========================================================================
# BATCH tests
# ===========================================================================

class TestBatchEndpoint:
    """POST /v1/content/batch"""

    _PERSISTED: Dict[str, Any] = {
        "content_id": "aaa-111",
        "created": True,
        "persisted": True,
        "discarded": False,
        "duplicate": False,
        "mode": "saved",
    }
    _DEDUPED: Dict[str, Any] = {
        "content_id": "bbb-222",
        "created": False,
        "persisted": True,
        "discarded": False,
        "duplicate": True,
        "mode": "deduplicated",
    }
    _DISCARDED: Dict[str, Any] = {
        "content_id": "ccc-333",
        "created": False,
        "persisted": False,
        "discarded": True,
        "duplicate": False,
        "mode": "discarded",
    }

    def test_b1_single_item_persisted(self, monkeypatch):
        monkeypatch.setattr(batch_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(create_content_minimal=lambda **_: self._PERSISTED))
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post("/v1/content/batch", json={"items": [{"content": "hello world"}]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["total"] == 1
        assert body["summary"]["persisted"] == 1
        assert body["results"][0]["ok"] is True
        assert body["results"][0]["index"] == 0

    def test_b2_mixed_outcomes(self, monkeypatch):
        outcomes = [self._PERSISTED, self._DEDUPED, self._DISCARDED]
        call_idx = {"i": 0}

        def _create(**_):
            r = outcomes[call_idx["i"]]
            call_idx["i"] += 1
            return r

        monkeypatch.setattr(batch_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(create_content_minimal=_create))
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post("/v1/content/batch", json={"items": [{"content": f"item {i}"} for i in range(3)]})
        assert resp.status_code == 200
        s = resp.json()["summary"]
        assert s["total"] == 3
        assert s["persisted"] == 1
        assert s["deduplicated"] == 1
        assert s["discarded"] == 1
        assert s["failed"] == 0

    def test_b3_item_exception_captured(self, monkeypatch):
        def _boom(**_): raise RuntimeError("db error")
        monkeypatch.setattr(batch_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(create_content_minimal=_boom))
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post("/v1/content/batch", json={"items": [{"content": "boom"}]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["failed"] == 1
        assert body["results"][0]["ok"] is False
        assert "db error" in body["results"][0]["error"]

    def test_b4_empty_items_rejected(self, monkeypatch):
        monkeypatch.setattr(batch_router, "ApiAdapter", lambda *a, **kw: MagicMock())
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post("/v1/content/batch", json={"items": []})
        assert resp.status_code == 422

    def test_b5_over_limit_rejected(self, monkeypatch):
        monkeypatch.setattr(batch_router, "ApiAdapter", lambda *a, **kw: MagicMock())
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post("/v1/content/batch", json={"items": [{"content": f"x{i}"} for i in range(51)]})
        assert resp.status_code == 422

    def test_b6_indices_are_sequential(self, monkeypatch):
        monkeypatch.setattr(batch_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(create_content_minimal=lambda **_: self._PERSISTED))
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post("/v1/content/batch", json={"items": [{"content": f"c{i}"} for i in range(5)]})
        assert resp.status_code == 200
        indices = [r["index"] for r in resp.json()["results"]]
        assert indices == list(range(5))

    def test_b7_partial_failure_rest_continue(self, monkeypatch):
        """One failing item must not abort subsequent items."""
        persisted = {**self._PERSISTED}

        def _side_effect(content=None, **kw):
            if content == "fail":
                raise RuntimeError("forced")
            return {**persisted, "content_id": "ok-id"}

        monkeypatch.setattr(batch_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(create_content_minimal=_side_effect))
        client = TestClient(_batch_app(monkeypatch))
        resp = client.post(
            "/v1/content/batch",
            json={"items": [{"content": "ok"}, {"content": "fail"}, {"content": "ok"}]},
        )
        body = resp.json()
        assert body["summary"]["persisted"] == 2
        assert body["summary"]["failed"] == 1


# ===========================================================================
# SIMILAR tests
# ===========================================================================

class TestSimilarEndpoint:
    """POST /v1/retrieval/similar"""

    _SOURCE = {"content_id": "src-001", "workspace_id": "00000000-0000-0000-0000-000000000002"}
    _RESULT_A = {"content_id": "res-001", "chunk_text": "memory systems", "score": 0.91}
    _RESULT_B = {"content_id": "res-002", "chunk_text": "retrieval ranking", "score": 0.85}

    def _patch_source(self, monkeypatch, *, exists=True, text="context brain memory retrieval"):
        monkeypatch.setattr(similar_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(get_content_minimal=lambda *_, **__: self._SOURCE if exists else None))
        monkeypatch.setattr(similar_router, "_fetch_source_text", lambda *a, **kw: text)

    def test_s1_returns_similar_results(self, monkeypatch):
        self._patch_source(monkeypatch)
        monkeypatch.setattr(similar_router, "RetrievalAdapter",
            lambda *a, **kw: SimpleNamespace(search=lambda **__: [self._RESULT_A, self._RESULT_B]))
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "src-001"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_content_id"] == "src-001"
        assert body["count"] == 2

    def test_s2_source_excluded_from_results(self, monkeypatch):
        results = [{"content_id": "src-001", "chunk_text": "self", "score": 1.0}, self._RESULT_A]
        self._patch_source(monkeypatch)
        monkeypatch.setattr(similar_router, "RetrievalAdapter",
            lambda *a, **kw: SimpleNamespace(search=lambda **__: results))
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "src-001"})
        ids = [r["content_id"] for r in resp.json()["results"]]
        assert "src-001" not in ids
        assert "res-001" in ids

    def test_s3_not_found_returns_404(self, monkeypatch):
        self._patch_source(monkeypatch, exists=False)
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "missing-id"})
        assert resp.status_code == 404

    def test_s4_empty_text_returns_422(self, monkeypatch):
        self._patch_source(monkeypatch, text="")
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "src"})
        assert resp.status_code == 422

    def test_s5_limit_respected(self, monkeypatch):
        many = [{"content_id": f"r-{i}", "chunk_text": f"text {i}", "score": 0.9 - i * 0.01} for i in range(20)]
        self._patch_source(monkeypatch)
        monkeypatch.setattr(similar_router, "RetrievalAdapter",
            lambda *a, **kw: SimpleNamespace(search=lambda **__: many))
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "src-001", "limit": 3})
        assert resp.json()["count"] == 3

    def test_s7_search_called_without_limit_kwarg(self, monkeypatch):
        """RetrievalAdapter.search has no limit parameter — the router must not pass one."""
        captured = {}

        def _search(**kw):
            captured.update(kw)
            return []

        self._patch_source(monkeypatch)
        monkeypatch.setattr(similar_router, "RetrievalAdapter",
            lambda *a, **kw: SimpleNamespace(search=_search))
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "src-001"})
        assert resp.status_code == 200
        assert "limit" not in captured
        assert captured["workspace_id"] == "00000000-0000-0000-0000-000000000002"

    def test_s8_body_workspace_is_ignored(self, monkeypatch):
        """Workspace isolation: caller-supplied workspace_id must not widen scope."""
        captured = {}

        def _get(content_id, workspace_id=None):
            captured["workspace_id"] = workspace_id
            return self._SOURCE

        monkeypatch.setattr(similar_router, "ApiAdapter",
            lambda *a, **kw: SimpleNamespace(get_content_minimal=_get))
        monkeypatch.setattr(similar_router, "_fetch_source_text", lambda *a, **kw: "text")
        monkeypatch.setattr(similar_router, "RetrievalAdapter",
            lambda *a, **kw: SimpleNamespace(search=lambda **__: []))
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar",
            json={"content_id": "src-001", "workspace_id": "99999999-9999-9999-9999-999999999999"})
        assert resp.status_code == 200
        assert captured["workspace_id"] == "00000000-0000-0000-0000-000000000002"

    def test_s6_limit_over_max_rejected(self, monkeypatch):
        client = TestClient(_similar_app(monkeypatch))
        resp = client.post("/v1/retrieval/similar", json={"content_id": "x", "limit": 99})
        assert resp.status_code == 422


# ===========================================================================
# FEEDBACK tests
# ===========================================================================

class TestFeedbackEndpoint:
    """POST /v1/retrieval/feedback"""

    def _mock_conn(self, feedback_id="fb-uuid-001"):
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.side_effect = [(None,), (feedback_id,)]
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        return mock_conn

    def test_f1_up_signal_recorded(self, monkeypatch):
        monkeypatch.setattr(feedback_router.psycopg2, "connect", lambda *a, **kw: self._mock_conn("fb-001"))
        client = TestClient(_feedback_app(monkeypatch))
        resp = client.post("/v1/retrieval/feedback", json={"content_id": "cid-123", "signal": "up"})
        assert resp.status_code == 200
        assert resp.json()["recorded"] is True
        assert "feedback_id" in resp.json()

    def test_f2_down_signal_recorded(self, monkeypatch):
        monkeypatch.setattr(feedback_router.psycopg2, "connect", lambda *a, **kw: self._mock_conn("fb-002"))
        client = TestClient(_feedback_app(monkeypatch))
        resp = client.post("/v1/retrieval/feedback",
            json={"content_id": "cid-456", "signal": "down", "query_text": "what is memory"})
        assert resp.status_code == 200
        assert resp.json()["recorded"] is True

    def test_f3_invalid_signal_rejected(self, monkeypatch):
        client = TestClient(_feedback_app(monkeypatch))
        resp = client.post("/v1/retrieval/feedback", json={"content_id": "cid-789", "signal": "meh"})
        assert resp.status_code == 422

    def test_f4_missing_content_id_rejected(self, monkeypatch):
        client = TestClient(_feedback_app(monkeypatch))
        resp = client.post("/v1/retrieval/feedback", json={"signal": "up"})
        assert resp.status_code == 422

    def test_f5_metadata_accepted(self, monkeypatch):
        monkeypatch.setattr(feedback_router.psycopg2, "connect", lambda *a, **kw: self._mock_conn("fb-005"))
        client = TestClient(_feedback_app(monkeypatch))
        resp = client.post("/v1/retrieval/feedback",
            json={"content_id": "cid-meta", "signal": "up", "metadata": {"source": "mcp", "rank": 1}})
        assert resp.status_code == 200
        assert resp.json()["recorded"] is True
