"""M8E — classify_content_node: deterministic, caller-specified node_type setter.

Production parity tool name, but the public contract is explicit: caller-specified,
deterministic, fixed vocabulary, NOT AI/provider classification.
"""

from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
import memory_lab.api.routers.content as content_router
from memory_lab.api.routers.content import VALID_NODE_TYPES
import memory_lab.mcp.tools as tools
from memory_lab.mcp.client import MemoryLabApiClient
from memory_lab.mcp.tools import APPROVED_TOOLS


WS = "00000000-0000-0000-0000-0000000000a1"
OTHER_WS = "00000000-0000-0000-0000-0000000000b2"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"
CONTENT = "00000000-0000-0000-0000-0000000000d4"


def test_valid_node_types_match_production_vocabulary():
    assert VALID_NODE_TYPES == frozenset({
        "decision", "fact", "hypothesis", "question", "playbook",
        "concept", "source", "task", "event", "raw_note",
    })


class FakeAdapter:
    rows = {}
    calls = []

    def __init__(self, database_url):
        self.database_url = database_url

    def set_node_type(self, content_id, node_type, workspace_id=None):
        self.__class__.calls.append({"content_id": content_id, "node_type": node_type, "workspace_id": workspace_id})
        row = self.__class__.rows.get((workspace_id, content_id))
        if not row:
            return None
        return {"content_id": content_id, "workspace_id": workspace_id, "node_type": node_type, "updated_at": "2026-01-01T00:00:00+00:00"}


def _client(monkeypatch, workspace_id=WS):
    FakeAdapter.rows = {}
    FakeAdapter.calls = []
    app = create_app()

    def override():
        return AuthContext(auth_subject_id=SUBJECT, subject_type="user", workspace_id=workspace_id, role="owner", auth_method="test")

    app.dependency_overrides[require_permission("content.update")] = override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                if "content.update" in [c.cell_contents for c in call.__closure__]:
                    app.dependency_overrides[call] = override

    monkeypatch.setattr(content_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(content_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/test"))
    return TestClient(app)


def test_api_set_node_type_success_deterministic_contract(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(WS, CONTENT)] = {"content_id": CONTENT, "workspace_id": WS}

    resp = client.patch(f"/v1/content/{CONTENT}/node-type", json={"node_type": "fact"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["content_id"] == CONTENT
    assert body["node_type"] == "fact"
    assert body["updated"] is True
    assert body["deterministic"] is True
    assert body["provider_backed"] is False
    assert body["classification_mode"] == "caller_specified"
    assert set(body["allowed_node_types"]) == set(VALID_NODE_TYPES)
    assert FakeAdapter.calls == [{"content_id": CONTENT, "node_type": "fact", "workspace_id": WS}]


def test_api_set_node_type_404_wrong_workspace(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(OTHER_WS, CONTENT)] = {"content_id": CONTENT, "workspace_id": OTHER_WS}

    resp = client.patch(f"/v1/content/{CONTENT}/node-type", json={"node_type": "fact"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "content not found"
    assert FakeAdapter.calls[0]["workspace_id"] == WS


def test_api_set_node_type_invalid_type_422_without_db_call(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)

    resp = client.patch(f"/v1/content/{CONTENT}/node-type", json={"node_type": "definitely_not_valid"})

    assert resp.status_code == 422
    assert FakeAdapter.calls == []


class RecordingClient(MemoryLabApiClient):
    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8000")

    def _request(self, method, path, *, params=None, json_body=None, workspace_id=None):
        return {"method": method, "path": path, "params": params, "json_body": json_body, "workspace_id": workspace_id}


def test_mcp_client_set_node_type_path_and_payload():
    call = RecordingClient().set_node_type(CONTENT, "decision", workspace_id=WS)
    assert call == {
        "method": "PATCH",
        "path": f"/v1/content/{CONTENT}/node-type",
        "params": None,
        "json_body": {"node_type": "decision"},
        "workspace_id": WS,
    }


def test_tool_classify_content_node_forwards_deterministically(monkeypatch):
    captured = {}

    class FakeClient:
        def set_node_type(self, content_id, node_type, workspace_id=None):
            captured.update(content_id=content_id, node_type=node_type, workspace_id=workspace_id)
            return {"content_id": content_id, "node_type": node_type, "updated": True}

    monkeypatch.setattr(tools, "_client", lambda: FakeClient())
    result = tools.classify_content_node(content_id=CONTENT, node_type="task", workspace_id=WS)
    assert captured == {"content_id": CONTENT, "node_type": "task", "workspace_id": WS}
    assert result["node_type"] == "task"


def test_classify_content_node_registered_and_count_is_32():
    assert APPROVED_TOOLS["classify_content_node"]
    assert len(APPROVED_TOOLS) == 34  # 32 parity + CF-003 anchors + CF-002 decisions-by-content
    server_source = Path("memory_lab/mcp/server.py").read_text()
    assert "APPROVED_TOOLS[\"classify_content_node\"]" in server_source
