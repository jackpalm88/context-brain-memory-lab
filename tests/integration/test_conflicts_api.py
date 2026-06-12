import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
from memory_lab.conflicts.models import ConflictSearchResponse

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.public_safe]

WS1 = "00000000-0000-0000-0000-000000000101"
WS2 = "00000000-0000-0000-0000-000000000102"


def _db_url():
    url = os.environ.get("CB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CB_TEST_DATABASE_URL not set")
    return url


def _client(workspace_id=WS1):
    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id="00000000-0000-0000-0000-000000000201",
            subject_type="user",
            workspace_id=workspace_id,
            role="owner",
            auth_method="test",
        )

    # require_permission(...) returns a closure; override the concrete callable
    # installed on routes instead of constructing a fresh closure.
    app.dependency_overrides[require_permission("retrieval.search")] = override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                closure_values = [cell.cell_contents for cell in call.__closure__]
                if "retrieval.search" in closure_values:
                    app.dependency_overrides[call] = override
    return TestClient(app)


class _DummyConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_conflicts_endpoint_result_shape_without_provider_or_db_side_effects(monkeypatch):
    from memory_lab.api.routers import conflicts as conflicts_router

    def fake_connect(_database_url):
        return _DummyConn()

    def fake_search(conn, **kwargs):
        assert conn is not None
        assert kwargs["workspace_id"] == WS1
        return ConflictSearchResponse(conflicts=[], count=0, workspace_id=WS1, workspace_source="test")

    monkeypatch.setattr(conflicts_router.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(conflicts_router, "search_conflict_candidates", fake_search)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    r = _client().post("/v1/conflicts/search", json={"scope": "b11"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflicts"] == []
    assert body["count"] == 0
    assert body["mode"] == "workspace_scoped_deterministic_conflict_candidates"
    assert body["truth_arbitration"] is False
    assert body["provider_backed_reasoning"] is False


def _insert_content(
    conn,
    *,
    workspace_id,
    content_id,
    text,
    memory_type="decision",
    confidence=0.9,
    scope="b11",
    is_current=None,
    supersedes=None,
):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s) ON CONFLICT (workspace_id) DO NOTHING",
            (workspace_id, f"ws-{workspace_id[-4:]}", "B11 Test Workspace"),
        )
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id, memory_type, classify_confidence, current_state_scope, is_current, cs_supersedes_content_id) VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::uuid)",
            (content_id, workspace_id, memory_type, confidence, scope, is_current, supersedes),
        )
        cur.execute(
            "INSERT INTO content_chunks (chunk_id, content_id, workspace_id, chunk_index, chunk_text) VALUES (%s::uuid, %s::uuid, %s::uuid, 0, %s)",
            (str(uuid.uuid4()), content_id, workspace_id, text),
        )
    conn.commit()


@pytest.fixture
def conn():
    with psycopg2.connect(_db_url()) as c:
        yield c
        with c.cursor() as cur:
            cur.execute("DELETE FROM content_chunks WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
            cur.execute("DELETE FROM cb_current_state_anchors WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
            cur.execute("DELETE FROM content_items WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
        c.commit()


def test_conflicts_endpoint_explicit_counterfinding_same_workspace(conn, monkeypatch):
    _insert_content(conn, workspace_id=WS1, content_id="10000000-0000-0000-0000-000000000001", text="scope: b11\nfinding: original")
    _insert_content(conn, workspace_id=WS1, content_id="10000000-0000-0000-0000-000000000002", text="scope: b11\ncounterfinding: b11")
    monkeypatch.setenv("DATABASE_URL", _db_url())
    r = _client().post("/v1/conflicts/search", json={"scope": "b11"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["truth_arbitration"] is False
    assert body["provider_backed_reasoning"] is False
    assert body["conflicts"][0]["conflict_type"] == "explicit_counterfinding"


def test_conflicts_endpoint_explicit_contradiction_same_workspace(conn):
    _insert_content(conn, workspace_id=WS1, content_id="10000000-0000-0000-0000-000000000003", text="scope: b11\nfinding: original")
    _insert_content(conn, workspace_id=WS1, content_id="10000000-0000-0000-0000-000000000004", text="scope: b11\ncontradicts: b11")
    body = _client().post("/v1/conflicts/search", json={"scope": "b11"}).json()
    assert body["conflicts"][0]["conflict_type"] == "explicit_contradiction"


def test_conflicts_endpoint_current_state_supersession_candidate(conn):
    old = "10000000-0000-0000-0000-000000000005"
    new = "10000000-0000-0000-0000-000000000006"
    _insert_content(conn, workspace_id=WS1, content_id=old, text="scope: b11\nold", is_current=False)
    _insert_content(conn, workspace_id=WS1, content_id=new, text="scope: b11\nnew", is_current=True, supersedes=old)
    body = _client().post("/v1/conflicts/search", json={"scope": "b11"}).json()
    assert any(c["conflict_type"] == "stale_current_tension" for c in body["conflicts"])


def test_conflicts_endpoint_workspace_isolation(conn):
    _insert_content(conn, workspace_id=WS1, content_id="10000000-0000-0000-0000-000000000007", text="scope: b11\nfinding")
    _insert_content(conn, workspace_id=WS2, content_id="10000000-0000-0000-0000-000000000008", text="scope: b11\ncontradicts: b11")
    body = _client(WS1).post("/v1/conflicts/search", json={"scope": "b11"}).json()
    assert body["conflicts"] == []


def test_conflicts_endpoint_discarded_content_not_visible(conn):
    _insert_content(conn, workspace_id=WS1, content_id="10000000-0000-0000-0000-000000000009", text="scope: b11\nfinding")
    body = _client().post("/v1/conflicts/search", json={"scope": "b11"}).json()
    assert body["conflicts"] == []


def test_retrieval_search_default_contract_unchanged(conn):
    r = _client().post("/v1/retrieval/search", json={"query": "b11"})
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert "conflicts" not in body
    assert body["mode"] == "workspace_scoped_deterministic_db"
