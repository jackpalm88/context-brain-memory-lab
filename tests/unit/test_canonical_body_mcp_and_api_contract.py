"""Patch 1 Phase E/F contract tests — REST route shape and MCP delegation.

DB-free (FakeAdapter / RecordingClient), complementing the live-DB proof in
tests/integration/test_canonical_body_api.py. Mirrors the established
pattern in tests/unit/test_m8a1_quick_summary.py.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
import memory_lab.api.routers.content as content_router
from memory_lab.mcp.client import MemoryLabApiClient
from memory_lab.mcp.tools import APPROVED_TOOLS

WS = "00000000-0000-0000-0000-0000000000e5"
OTHER_WS = "00000000-0000-0000-0000-0000000000f6"
SUBJECT = "00000000-0000-0000-0000-000000000107"
CONTENT = "00000000-0000-0000-0000-000000000208"


class FakeAdapter:
    rows = {}
    calls = []

    def __init__(self, database_url):
        self.database_url = database_url

    def get_canonical_body(self, content_id, workspace_id=None):
        self.__class__.calls.append({"content_id": content_id, "workspace_id": workspace_id})
        return self.__class__.rows.get((workspace_id, content_id))


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

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                closure_values = [cell.cell_contents for cell in call.__closure__]
                if "content.read" in closure_values:
                    app.dependency_overrides[call] = override

    monkeypatch.setattr(content_router, "ApiAdapter", FakeAdapter)
    from types import SimpleNamespace
    monkeypatch.setattr(content_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/test"))
    return TestClient(app)


def test_api_canonical_body_hash_verified_shape(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(WS, CONTENT)] = {
        "content_id": CONTENT,
        "workspace_id": WS,
        "updated_at": "2026-09-22T00:00:00+00:00",
        "body": "exact body",
        "body_sha256": "abc123",
        "fidelity": "hash-verified",
        "hash_semantics": "sha256(raw_submitted_body.encode('utf-8')); no normalization at hash time",
    }

    resp = client.get(f"/v1/content/{CONTENT}/canonical-body")

    assert resp.status_code == 200
    body = resp.json()
    assert body["fidelity"] == "hash-verified"
    assert body["body"] == "exact body"
    assert body["body_sha256"] == "abc123"
    assert FakeAdapter.calls == [{"content_id": CONTENT, "workspace_id": WS}]


def test_api_canonical_body_404_for_unknown_id(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)

    resp = client.get(f"/v1/content/{CONTENT}/canonical-body")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "content not found"


def test_api_canonical_body_404_for_wrong_workspace(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(OTHER_WS, CONTENT)] = {
        "content_id": CONTENT, "workspace_id": OTHER_WS, "updated_at": None,
        "body": "leaked?", "body_sha256": "x", "fidelity": "hash-verified", "hash_semantics": "n/a",
    }

    resp = client.get(f"/v1/content/{CONTENT}/canonical-body")

    assert resp.status_code == 404
    assert FakeAdapter.calls[0]["workspace_id"] == WS


class RecordingClient(MemoryLabApiClient):
    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8000")
        self.calls = []

    def _request(self, method, path, *, params=None, json_body=None, workspace_id=None):
        call = {"method": method, "path": path, "params": params, "json_body": json_body, "workspace_id": workspace_id}
        self.calls.append(call)
        return call


def test_mcp_client_canonical_body_path():
    client = RecordingClient()

    result = client.canonical_body_get(CONTENT, workspace_id=WS)

    assert result == {
        "method": "GET",
        "path": f"/v1/content/{CONTENT}/canonical-body",
        "params": None,
        "json_body": None,
        "workspace_id": WS,
    }


def test_get_canonical_body_verified_tool_registered_and_wired():
    assert "get_canonical_body_verified" in APPROVED_TOOLS
    server_source = Path("memory_lab/mcp/server.py").read_text()
    http_server_source = Path("memory_lab/mcp/http_server.py").read_text()
    assert 'APPROVED_TOOLS["get_canonical_body_verified"]' in server_source
    assert 'APPROVED_TOOLS["get_canonical_body_verified"]' in http_server_source
