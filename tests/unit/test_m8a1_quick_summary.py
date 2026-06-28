from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import ROLE_PERMISSIONS, require_permission
from memory_lab.api.main import create_app
import memory_lab.api.routers.content as content_router
from memory_lab.mcp.client import MemoryLabApiClient
from memory_lab.mcp.tools import APPROVED_TOOLS


WS = "00000000-0000-0000-0000-0000000000a1"
OTHER_WS = "00000000-0000-0000-0000-0000000000b2"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"
CONTENT = "00000000-0000-0000-0000-0000000000d4"


class FakeAdapter:
    rows = {}
    calls = []

    def __init__(self, database_url):
        self.database_url = database_url

    def set_quick_summary(self, content_id, quick_summary, workspace_id=None):
        self.__class__.calls.append({
            "content_id": content_id,
            "quick_summary": quick_summary,
            "workspace_id": workspace_id,
            "database_url": self.database_url,
        })
        row = self.__class__.rows.get((workspace_id, content_id))
        if not row:
            return None
        return {
            "content_id": content_id,
            "workspace_id": workspace_id,
            "quick_summary": quick_summary,
            "updated": True,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }


def _client(monkeypatch, workspace_id=WS):
    FakeAdapter.rows = {}
    FakeAdapter.calls = []
    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id=SUBJECT,
            subject_type="user",
            workspace_id=workspace_id,
            role="owner",
            auth_method="test",
        )

    app.dependency_overrides[require_permission("content.update")] = override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                closure_values = [cell.cell_contents for cell in call.__closure__]
                if "content.update" in closure_values:
                    app.dependency_overrides[call] = override

    monkeypatch.setattr(content_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(content_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/test"))
    return TestClient(app)


def test_api_set_quick_summary_success_workspace_scoped(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(WS, CONTENT)] = {"content_id": CONTENT, "workspace_id": WS}

    response = client.patch(f"/v1/content/{CONTENT}/quick-summary", json={"quick_summary": "short summary"})

    assert response.status_code == 200
    body = response.json()
    assert body["content_id"] == CONTENT
    assert body["workspace_id"] == WS
    assert body["quick_summary"] == "short summary"
    assert body["updated"] is True
    assert FakeAdapter.calls == [{
        "content_id": CONTENT,
        "quick_summary": "short summary",
        "workspace_id": WS,
        "database_url": "postgresql://unit/test",
    }]


def test_api_set_quick_summary_404_for_wrong_workspace(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(OTHER_WS, CONTENT)] = {"content_id": CONTENT, "workspace_id": OTHER_WS}

    response = client.patch(f"/v1/content/{CONTENT}/quick-summary", json={"quick_summary": "summary"})

    assert response.status_code == 404
    assert response.json()["detail"] == "content not found"
    assert FakeAdapter.calls[0]["workspace_id"] == WS


def test_api_set_quick_summary_rejects_over_500_chars(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)

    response = client.patch(f"/v1/content/{CONTENT}/quick-summary", json={"quick_summary": "x" * 501})

    assert response.status_code == 422
    assert FakeAdapter.calls == []


class RecordingClient(MemoryLabApiClient):
    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8000")
        self.calls = []

    def _request(self, method, path, *, params=None, json_body=None, workspace_id=None):
        call = {
            "method": method,
            "path": path,
            "params": params,
            "json_body": json_body,
            "workspace_id": workspace_id,
        }
        self.calls.append(call)
        return call


def test_mcp_client_set_quick_summary_path_and_payload():
    client = RecordingClient()

    result = client.set_quick_summary(CONTENT, "summary", workspace_id=WS)

    assert result == {
        "method": "PATCH",
        "path": f"/v1/content/{CONTENT}/quick-summary",
        "params": None,
        "json_body": {"quick_summary": "summary"},
        "workspace_id": WS,
    }


def test_content_update_permission_allows_writer_surface():
    assert ROLE_PERMISSIONS["content.update"] == {"owner", "admin", "writer", "service_agent"}


def test_set_quick_summary_tool_registered_and_counted():
    assert APPROVED_TOOLS["set_quick_summary"]
    assert len(APPROVED_TOOLS) == 30
    server_source = Path("memory_lab/mcp/server.py").read_text()
    assert "APPROVED_TOOLS[\"set_quick_summary\"]" in server_source
