"""M9B Provenance Completion — authenticated actor persisted on domain writes.

Identity is SERVER-DERIVED (AuthContext.auth_subject_id); callers cannot supply it.
NULL created_by_subject = predates provenance / unknown (no fabricated backfill).
"""

from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app

WS = "00000000-0000-0000-0000-0000000000a1"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"
OTHER = "11111111-1111-1111-1111-111111111111"
CONTENT = "00000000-0000-0000-0000-0000000000d4"
HUB = "00000000-0000-0000-0000-0000000000e5"


class FakeCursor:
    def __init__(self, row):
        self.executed = []
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self.cursor_obj

    def commit(self):
        pass


def _executed_text(cur):
    return " || ".join(sql for sql, _ in cur.executed)


def _all_params(cur):
    flat = []
    for _, params in cur.executed:
        if params:
            flat.extend(list(params))
    return flat


def test_hub_store_create_persists_created_by_subject():
    from memory_lab.graph.hub_store import HubStore
    store = HubStore.__new__(HubStore)
    cur = FakeCursor({"hub_id": HUB, "title": "T", "type": "topic", "description": None,
                      "aliases": [], "related_terms": [], "status": "active",
                      "owner_defined": True, "workspace_id": WS, "workspace_uuid": WS,
                      "created_at": None, "updated_at": None})
    store._conn = lambda: FakeConn(cur)
    store.create_hub(title="T", created_by_subject=SUBJECT, workspace_uuid=WS)
    assert "created_by_subject" in _executed_text(cur)
    assert SUBJECT in _all_params(cur)


def test_hub_store_link_content_persists_created_by_subject():
    from memory_lab.graph.hub_store import HubStore
    store = HubStore.__new__(HubStore)
    cur = FakeCursor({"hub_id": HUB})
    store._conn = lambda: FakeConn(cur)
    store.link_content(HUB, CONTENT, created_by_subject=SUBJECT)
    assert "cb_hub_content" in _executed_text(cur)
    assert "created_by_subject" in _executed_text(cur)
    assert SUBJECT in _all_params(cur)


def test_decision_store_create_persists_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    from memory_lab.decisions.models import DecisionCreate
    store = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor({"decision_id": "d1", "title": "T", "decision_status": "active", "created_at": None})
    store._conn = lambda: FakeConn(cur)
    payload = DecisionCreate(title="T", decision_reason="why")
    store.create_decision(payload, workspace_id=WS, created_by_subject=SUBJECT)
    text = _executed_text(cur)
    assert "cb_decision_nodes" in text and "created_by_subject" in text
    assert SUBJECT in _all_params(cur)


def test_content_create_minimal_persists_created_by_subject():
    from memory_lab.api.services.api_adapter import ApiAdapter
    adapter = ApiAdapter.__new__(ApiAdapter)
    adapter.database_url = "postgresql://unit/test"
    cur = FakeCursor({"content_id": CONTENT})
    adapter._conn = lambda: FakeConn(cur)
    adapter._find_duplicate_content_id = lambda *a, **k: None
    adapter.create_content_minimal(content="hello world", workspace_id=WS, created_by_subject=SUBJECT)
    text = _executed_text(cur)
    assert "INSERT INTO content_items" in text and "created_by_subject" in text
    assert SUBJECT in _all_params(cur)


def _app_with_perms(perms):
    app = create_app()

    def override():
        return AuthContext(auth_subject_id=SUBJECT, subject_type="user", workspace_id=WS, role="owner", auth_method="test")

    for perm in perms:
        app.dependency_overrides[require_permission(perm)] = override
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in getattr(dependant, "dependencies", []):
                call = getattr(dep, "call", None)
                if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                    if perm in [c.cell_contents for c in call.__closure__]:
                        app.dependency_overrides[call] = override
    return app


class FakeAdapter:
    captured = {}

    def __init__(self, database_url):
        pass

    def create_content_minimal(self, content=None, workspace_id=None, workspace_source=None, created_by_subject=None):
        FakeAdapter.captured = {"created_by_subject": created_by_subject, "workspace_id": workspace_id}
        return {"content_id": CONTENT, "persisted": True, "created_by_subject": created_by_subject}

    def create_edge(self, payload, workspace_id=None, created_by=None):
        FakeAdapter.captured = {"created_by": created_by, "workspace_id": workspace_id, "payload": payload}
        return {"edge_id": "e1", "created_by": created_by}

    def approve_inferred_edge(self, **kwargs):
        FakeAdapter.captured = kwargs
        return {"edge_id": "e1", "created_by": kwargs.get("created_by")}


def test_router_content_create_uses_auth_subject_not_body(monkeypatch):
    import memory_lab.api.routers.content as content_router
    app = _app_with_perms(["content.create"])
    monkeypatch.setattr(content_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(content_router, "get_settings", lambda: SimpleNamespace(database_url="x"))
    client = TestClient(app)
    resp = client.post("/v1/content", json={"content": "x", "created_by_subject": OTHER, "workspace_id": OTHER})
    assert resp.status_code == 200
    assert FakeAdapter.captured["created_by_subject"] == SUBJECT
    assert FakeAdapter.captured["workspace_id"] == WS


def test_router_edge_create_threads_auth_subject(monkeypatch):
    import memory_lab.api.routers.edges as edges_router
    app = _app_with_perms(["edges.create"])
    monkeypatch.setattr(edges_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(edges_router, "get_settings", lambda: SimpleNamespace(database_url="x"))
    client = TestClient(app)
    resp = client.post("/v1/edges", json={"source_hub_id": HUB, "target_hub_id": CONTENT, "edge_type": "related"})
    assert resp.status_code == 200
    assert FakeAdapter.captured["created_by"] == SUBJECT


def test_router_approve_inferred_edge_threads_auth_subject(monkeypatch):
    import memory_lab.api.routers.edges as edges_router
    app = _app_with_perms(["edges.create"])
    monkeypatch.setattr(edges_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(edges_router, "get_settings", lambda: SimpleNamespace(database_url="x"))
    client = TestClient(app)
    resp = client.post("/v1/edges/inferred/approve", json={"source_hub_id": HUB, "target_hub_id": CONTENT, "edge_type": "related"})
    assert resp.status_code == 200
    assert FakeAdapter.captured["created_by"] == SUBJECT


def test_edge_create_request_has_no_caller_actor_field():
    from memory_lab.api.routers.edges import EdgeCreateRequest
    assert "created_by" not in EdgeCreateRequest.model_fields
    assert "created_by_subject" not in EdgeCreateRequest.model_fields


def test_migration_033_additive_idempotent_no_backfill():
    sql = Path("migrations/033_add_actor_provenance.sql").read_text()
    for table in ("content_items", "cb_hubs", "cb_hub_content"):
        assert f"ALTER TABLE {table}" in sql
    assert sql.count("ADD COLUMN IF NOT EXISTS created_by_subject") >= 3
    assert "UPDATE" not in sql.upper()
    assert "NULL" in sql
