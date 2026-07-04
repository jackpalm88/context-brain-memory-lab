"""b8 defect-fix regressions (Hermes DX-2/DX-3 audit, 2026-07-04).

Contracts pinned here were all broken live while the hermetic DX suites passed,
because those suites faked adapters or mounted routers onto private apps:

  F1  /v1/audit/keywords is registered on the REAL create_app()
  F2  batch passes auth-derived workspace + created_by_subject provenance
  F3  batch ignores a body-supplied workspace_id (workspace isolation)
  F4  similar source text comes from content_chunks (content_items has no body)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.main import create_app
import memory_lab.api.routers.batch as batch_router
import memory_lab.api.dependencies.auth as _auth_mod
import memory_lab.api.workspace_context as _ws_mod
from memory_lab.api.workspace_context import WorkspaceContext

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000002"
SUBJECT = "00000000-0000-0000-0000-000000000001"

_MOCK_AUTH = AuthContext(
    auth_subject_id=SUBJECT,
    subject_type="user",
    workspace_id=WS,
    role="owner",
    auth_method="api_key",
)

_FAKE_WORKSPACE = WorkspaceContext(
    workspace_id=WS, source="db_default", is_default=True,
    local_dev_default_used=False, slug="unit-test",
)

_FAKE_SETTINGS = SimpleNamespace(
    database_url="postgresql://unit:test@localhost/testdb",
    provider_embeddings_enabled=False,
)


def _patch_auth(monkeypatch):
    monkeypatch.setattr(_ws_mod, "resolve_workspace_context", lambda *a, **kw: _FAKE_WORKSPACE)
    monkeypatch.setattr(_auth_mod, "resolve_workspace_context", lambda *a, **kw: _FAKE_WORKSPACE)
    monkeypatch.setattr(_auth_mod, "resolve_auth_context", lambda perm, ws, authz: _MOCK_AUTH)


def test_f1_keywords_route_registered_on_real_app():
    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/v1/audit/keywords" in paths


def test_f2_f3_batch_uses_auth_scope_and_provenance(monkeypatch):
    captured = []

    def _create(**kw):
        captured.append(kw)
        return {"content_id": "x", "persisted": True, "duplicate": False}

    _patch_auth(monkeypatch)
    monkeypatch.setattr(batch_router, "get_settings", lambda: _FAKE_SETTINGS)
    monkeypatch.setattr(batch_router, "ApiAdapter",
        lambda *a, **kw: SimpleNamespace(create_content_minimal=_create))

    client = TestClient(create_app())
    resp = client.post(
        "/v1/content/batch",
        json={"items": [
            {"content": "plain item"},
            # F3: body workspace must be ignored, not honored (pydantic drops it)
            {"content": "attempted override", "workspace_id": "99999999-9999-9999-9999-999999999999"},
        ]},
    )

    assert resp.status_code == 200
    assert len(captured) == 2
    for kw in captured:
        assert kw["workspace_id"] == WS
        assert kw["created_by_subject"] == SUBJECT
    assert resp.json()["summary"]["persisted"] == 2


def test_f4_similar_fetches_text_from_chunks(monkeypatch):
    """_fetch_source_text queries content_chunks, workspace-scoped."""
    import memory_lab.api.routers.similar as similar_router

    executed = {}

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            executed["sql"] = " ".join(sql.split())
            executed["params"] = params

        def fetchall(self):
            return [("chunk one text",), ("chunk two text",)]

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    monkeypatch.setattr(similar_router.psycopg2, "connect", lambda *a, **kw: _Conn())
    text = similar_router._fetch_source_text("db://x", "cid-1", WS)

    assert text == "chunk one text chunk two text"
    assert "FROM content_chunks" in executed["sql"]
    assert "workspace_id = %s::uuid" in executed["sql"]
    assert executed["params"][0] == "cid-1"
    assert executed["params"][1] == WS
