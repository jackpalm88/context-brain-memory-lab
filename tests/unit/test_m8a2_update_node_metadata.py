from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
import memory_lab.api.routers.content as content_router
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.mcp.client import MemoryLabApiClient
from memory_lab.mcp.tools import APPROVED_TOOLS


WS = "00000000-0000-0000-0000-0000000000a1"
OTHER_WS = "00000000-0000-0000-0000-0000000000b2"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"
CONTENT = "00000000-0000-0000-0000-0000000000d4"
CREATED = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
UPDATED = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


class FakeAdapter:
    rows = {}
    calls = []

    def __init__(self, database_url):
        self.database_url = database_url

    def get_content_metadata(self, content_id, workspace_id=None):
        self.__class__.calls.append({
            "content_id": content_id,
            "workspace_id": workspace_id,
            "database_url": self.database_url,
        })
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

    app.dependency_overrides[require_permission("content.read")] = override
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
    monkeypatch.setattr(content_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/test"))
    return TestClient(app)


def _metadata_row(domain="governance", word_count=42):
    return {
        "content_id": CONTENT,
        "node_type": "fact",
        "quick_summary": "short metadata summary",
        "memory_type": "anchor",
        "domain": domain,
        "word_count": word_count,
        "created_by_subject": SUBJECT,
        "created_at": CREATED.isoformat(),
        "updated_at": UPDATED.isoformat(),
    }


def test_api_get_content_metadata_success_workspace_scoped_and_no_full_text(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(WS, CONTENT)] = _metadata_row()

    response = client.get(f"/v1/content/{CONTENT}/metadata")

    assert response.status_code == 200
    body = response.json()
    assert body == _metadata_row()
    assert "full_text" not in body
    assert "chunk_text" not in body
    assert FakeAdapter.calls == [{
        "content_id": CONTENT,
        "workspace_id": WS,
        "database_url": "postgresql://unit/test",
    }]


def test_api_get_content_metadata_404_for_wrong_workspace(monkeypatch):
    client = _client(monkeypatch, workspace_id=WS)
    FakeAdapter.rows[(OTHER_WS, CONTENT)] = _metadata_row()

    response = client.get(f"/v1/content/{CONTENT}/metadata")

    assert response.status_code == 404
    assert response.json()["detail"] == "content not found"
    assert FakeAdapter.calls[0]["workspace_id"] == WS


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


def _adapter_with_row(row):
    adapter = ApiAdapter.__new__(ApiAdapter)
    adapter.database_url = "postgresql://unit/test"
    cursor = FakeCursor(row)
    adapter._conn = lambda: FakeConn(cursor)
    return adapter, cursor


def test_api_adapter_get_content_metadata_aggregates_word_count_and_joins_domain():
    adapter, cursor = _adapter_with_row({
        "content_id": CONTENT,
        "node_type": "fact",
        "quick_summary": "summary",
        "memory_type": "anchor",
        "domain": "governance",
        "word_count": 42,
        "created_by_subject": SUBJECT,
        "created_at": CREATED,
        "updated_at": UPDATED,
    })

    result = adapter.get_content_metadata(CONTENT, workspace_id=WS)

    assert result == {
        "content_id": CONTENT,
        "node_type": "fact",
        "quick_summary": "summary",
        "memory_type": "anchor",
        # EB-1: current-state fields are part of every direct read
        "is_current": None,
        "current_state_scope": None,
        "cs_supersedes_content_id": None,
        "domain": "governance",
        "word_count": 42,
        "created_by_subject": SUBJECT,
        "created_at": CREATED.isoformat(),
        "updated_at": UPDATED.isoformat(),
    }
    assert "cb_discovered_domains" in cursor.sql
    assert "dd.domain_name AS domain" in cursor.sql
    assert "COALESCE(sum(ch.word_count), 0)::int AS word_count" in cursor.sql
    assert "ch.chunk_text" not in cursor.sql
    assert cursor.params == (CONTENT, WS)


def test_api_adapter_get_content_metadata_allows_null_domain_and_no_full_text():
    adapter, _ = _adapter_with_row({
        "content_id": CONTENT,
        "node_type": None,
        "quick_summary": None,
        "memory_type": None,
        "domain": None,
        "word_count": 0,
        "created_at": CREATED,
        "updated_at": UPDATED,
    })

    result = adapter.get_content_metadata(CONTENT, workspace_id=WS)

    assert result["domain"] is None
    assert result["word_count"] == 0
    assert "full_text" not in result


def test_api_adapter_get_content_metadata_returns_none_for_not_found():
    adapter, _ = _adapter_with_row(None)

    assert adapter.get_content_metadata(CONTENT, workspace_id=WS) is None


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


def test_mcp_client_update_node_metadata_path():
    client = RecordingClient()

    result = client.update_node_metadata(CONTENT, workspace_id=WS)

    assert result == {
        "method": "GET",
        "path": f"/v1/content/{CONTENT}/metadata",
        "params": None,
        "json_body": None,
        "workspace_id": WS,
    }


def test_update_node_metadata_tool_registered_and_counted():
    assert APPROVED_TOOLS["update_node_metadata"]
    assert len(APPROVED_TOOLS) == 34  # 32 parity + CF-003 anchors + CF-002 decisions-by-content
    server_source = Path("memory_lab/mcp/server.py").read_text()
    assert "APPROVED_TOOLS[\"update_node_metadata\"]" in server_source
