"""M8D2 — real include_inferred / include_curated filters for graph snapshot.

Intentional PUBLIC IMPROVEMENT over production (where include_inferred is a no-op):
public honors both flags using the edge origin. list_graph_snapshot stays a
flag-forwarding alias (production parity: "spec-canonical name").
"""

from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
import memory_lab.api.routers.graph as graph_router
from memory_lab.api.services.api_adapter import filter_snapshot_edges, INFERRED_EDGE_ORIGINS
import memory_lab.mcp.tools as tools
from memory_lab.mcp.client import MemoryLabApiClient


WS = "00000000-0000-0000-0000-0000000000a1"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"


def _edges():
    return [
        {"id": "e1", "origin": "manual"},
        {"id": "e2", "origin": "inferred_approved"},
        {"id": "e3", "origin": "ai_suggested"},
        {"id": "e4", "origin": "migration_localStorage"},
        {"id": "e5", "origin": None},
    ]


# ---- pure filter helper ----

def test_inferred_origins_set_is_explicit():
    assert INFERRED_EDGE_ORIGINS == {"inferred_approved", "ai_suggested"}


def test_both_true_returns_all_edges():
    out = filter_snapshot_edges(_edges(), include_inferred=True, include_curated=True)
    assert {e["id"] for e in out} == {"e1", "e2", "e3", "e4", "e5"}


def test_exclude_inferred_returns_curated_only():
    out = filter_snapshot_edges(_edges(), include_inferred=False, include_curated=True)
    assert {e["id"] for e in out} == {"e1", "e4", "e5"}


def test_exclude_curated_returns_inferred_only():
    out = filter_snapshot_edges(_edges(), include_inferred=True, include_curated=False)
    assert {e["id"] for e in out} == {"e2", "e3"}


def test_both_false_returns_empty():
    out = filter_snapshot_edges(_edges(), include_inferred=False, include_curated=False)
    assert out == []


# ---- MCP client param mapping ----

class RecordingClient(MemoryLabApiClient):
    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8000")

    def _request(self, method, path, *, params=None, json_body=None, workspace_id=None):
        return {"method": method, "path": path, "params": params, "json_body": json_body, "workspace_id": workspace_id}


def test_client_graph_snapshot_sends_filter_params():
    client = RecordingClient()
    call = client.graph_snapshot(include_inferred=False, include_curated=True, workspace_id=WS)
    assert call["path"] == "/v1/graph/snapshot"
    assert call["params"] == {"include_inferred": "false", "include_curated": "true"}
    assert call["workspace_id"] == WS


# ---- MCP tool forwards flags; list is a flag-forwarding alias ----

def test_tool_get_graph_snapshot_forwards_flags(monkeypatch):
    captured = {}

    class FakeClient:
        def graph_snapshot(self, include_inferred=True, include_curated=True, workspace_id=None):
            captured.update(include_inferred=include_inferred, include_curated=include_curated, workspace_id=workspace_id)
            return {"ok": True}

    monkeypatch.setattr(tools, "_client", lambda: FakeClient())
    tools.get_graph_snapshot(include_inferred=False, include_curated=True, workspace_id=WS)
    assert captured == {"include_inferred": False, "include_curated": True, "workspace_id": WS}


def test_tool_list_graph_snapshot_is_flag_forwarding_alias(monkeypatch):
    captured = {}

    class FakeClient:
        def graph_snapshot(self, include_inferred=True, include_curated=True, workspace_id=None):
            captured.update(include_inferred=include_inferred, include_curated=include_curated, workspace_id=workspace_id)
            return {"ok": True}

    monkeypatch.setattr(tools, "_client", lambda: FakeClient())
    tools.list_graph_snapshot(include_inferred=True, include_curated=False, workspace_id=WS)
    assert captured == {"include_inferred": True, "include_curated": False, "workspace_id": WS}


# ---- API router threads params + workspace scoping ----

class FakeAdapter:
    calls = []

    def __init__(self, database_url):
        self.database_url = database_url

    def get_graph_snapshot(self, include_inferred=True, include_curated=True, workspace_id=None):
        self.__class__.calls.append({
            "include_inferred": include_inferred,
            "include_curated": include_curated,
            "workspace_id": workspace_id,
        })
        return {"nodes": [], "edges": [], "stats": {}}


def _client_app(monkeypatch):
    FakeAdapter.calls = []
    app = create_app()

    def override():
        return AuthContext(auth_subject_id=SUBJECT, subject_type="user", workspace_id=WS, role="owner", auth_method="test")

    app.dependency_overrides[require_permission("hubs.read")] = override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                if "hubs.read" in [c.cell_contents for c in call.__closure__]:
                    app.dependency_overrides[call] = override

    monkeypatch.setattr(graph_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(graph_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/test"))
    return TestClient(app)


def test_api_snapshot_threads_filters_and_workspace(monkeypatch):
    client = _client_app(monkeypatch)
    resp = client.get("/v1/graph/snapshot", params={"include_inferred": "false", "include_curated": "true"})
    assert resp.status_code == 200
    assert FakeAdapter.calls == [{"include_inferred": False, "include_curated": True, "workspace_id": WS}]


def test_api_snapshot_defaults_both_true(monkeypatch):
    client = _client_app(monkeypatch)
    resp = client.get("/v1/graph/snapshot")
    assert resp.status_code == 200
    assert FakeAdapter.calls == [{"include_inferred": True, "include_curated": True, "workspace_id": WS}]
