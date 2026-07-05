"""Unit tests — EB-FIX: the three v1.0 epistemic blockers.

Shared root (Architecture Review A6): the system stayed silent about truth it
already knew. Per the v1.0 exception policy these fixes eliminate an epistemic
blocker, expand no capability, touch no frozen mechanism, and only improve
truthfulness of observable behavior.

EB-1: GET read surfaces expose resolver-owned current-state fields.
EB-2: empty content is a loud failure (422 / inline batch error), never a
      silent persisted=true.
EB-3: a skipped current-state resolver is visible in the save response.

Pure-Python; no DB; no provider calls.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.main import create_app
from memory_lab.current_state.projection import (
    CURRENT_STATE_FIELDS,
    current_state_group_by_sql,
    current_state_select_sql,
    project_current_state,
)

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-0000000000a1"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"
CONTENT = "00000000-0000-0000-0000-0000000000d4"
DB = "postgresql://unit/test"


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
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        pass


def _adapter_with_row(row):
    from memory_lab.api.services.api_adapter import ApiAdapter

    adapter = ApiAdapter.__new__(ApiAdapter)
    adapter.database_url = DB
    cur = FakeCursor(row)
    adapter._conn = lambda: FakeConn(cur)
    return adapter, cur


# ---------------------------------------------------------------------------
# EB-1 — GET read surfaces expose current-state
# ---------------------------------------------------------------------------

def test_projection_helper_is_canonical():
    assert CURRENT_STATE_FIELDS == ("is_current", "current_state_scope", "cs_supersedes_content_id")
    sql = current_state_select_sql("ci")
    assert "ci.is_current" in sql and "ci.current_state_scope" in sql
    assert "cs_supersedes_content_id::text" in sql
    assert current_state_group_by_sql("ci").count("ci.") == 3
    assert project_current_state({"is_current": True}) == {
        "is_current": True, "current_state_scope": None, "cs_supersedes_content_id": None,
    }


def test_get_content_minimal_exposes_current_state():
    row = {"content_id": CONTENT, "is_current": False,
           "current_state_scope": "message-queue", "cs_supersedes_content_id": None}
    adapter, cur = _adapter_with_row(row)
    result = adapter.get_content_minimal(CONTENT, workspace_id=WS)
    sql = cur.executed[0][0]
    assert "is_current" in sql and "current_state_scope" in sql and "cs_supersedes_content_id" in sql
    assert result["is_current"] is False
    assert result["current_state_scope"] == "message-queue"
    assert "cs_supersedes_content_id" in result


def test_get_content_metadata_exposes_current_state():
    row = {"content_id": CONTENT, "is_current": True,
           "current_state_scope": "design-tooling", "cs_supersedes_content_id": "older-id"}
    adapter, cur = _adapter_with_row(row)
    result = adapter.get_content_metadata(CONTENT, workspace_id=WS)
    sql = cur.executed[0][0]
    assert "is_current" in sql and "GROUP BY" in sql
    assert result["is_current"] is True
    assert result["current_state_scope"] == "design-tooling"
    assert result["cs_supersedes_content_id"] == "older-id"


# ---------------------------------------------------------------------------
# EB-2 — empty content fails loudly
# ---------------------------------------------------------------------------

def _app_with_perms(perms):
    from memory_lab.api.dependencies.auth import require_permission

    app = create_app()

    def override():
        return AuthContext(auth_subject_id=SUBJECT, subject_type="user",
                           workspace_id=WS, role="owner", auth_method="test")

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


@pytest.mark.parametrize("body", [{}, {"content": None}, {"content": ""}, {"content": "   "}])
def test_post_content_empty_returns_422(body):
    client = TestClient(_app_with_perms(["content.create"]))
    resp = client.post("/v1/content", json=body)
    assert resp.status_code == 422
    assert "non-empty" in resp.text


def test_post_content_valid_passes_validation(monkeypatch):
    import memory_lab.api.routers.content as content_router

    class FakeAdapter:
        def __init__(self, database_url, embedding_backend=None):
            pass

        def create_content_minimal(self, **kwargs):
            return {"content_id": CONTENT, "persisted": True}

    app = _app_with_perms(["content.create"])
    monkeypatch.setattr(content_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(content_router, "get_settings", lambda: SimpleNamespace(database_url=DB))
    resp = TestClient(app).post("/v1/content", json={"content": "Decision: real content."})
    assert resp.status_code == 200
    assert resp.json()["persisted"] is True


def test_batch_empty_items_fail_inline_without_aborting(monkeypatch):
    import memory_lab.api.routers.batch as batch_router

    class FakeAdapter:
        def __init__(self, database_url, embedding_backend=None):
            pass

        def create_content_minimal(self, content=None, **kwargs):
            return {"content_id": CONTENT, "persisted": True}

    app = _app_with_perms(["content.create"])
    monkeypatch.setattr(batch_router, "ApiAdapter", FakeAdapter)
    monkeypatch.setattr(batch_router, "get_settings", lambda: SimpleNamespace(database_url=DB))
    resp = TestClient(app).post("/v1/content/batch", json={"items": [
        {"content": "Decision: valid item."}, {"content": ""}, {}, {"content": "Another valid."},
    ]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == {"total": 4, "persisted": 2, "deduplicated": 0, "discarded": 0, "failed": 2}
    failed = [r for r in body["results"] if not r["ok"]]
    assert {r["index"] for r in failed} == {1, 2}
    assert all("non-empty" in r["error"] for r in failed)


# ---------------------------------------------------------------------------
# EB-3 — skipped resolver is visible in the save response
# ---------------------------------------------------------------------------

def _run_create(adapter_confidence, resolver_mock):
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.governance.tier_router import TierDecision

    adapter = ApiAdapter(DB)
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {"content_id": CONTENT}
    mock_conn.cursor.return_value = mock_cur
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    classify_meta = {"classify_confidence": adapter_confidence, "memory_type": "raw_memory",
                     "memory_sub_type": None, "signals": [], "project_topic": None, "domain_hint": None}
    fake_event = MagicMock()
    fake_event.scores = MagicMock(composite=0.8, quality=0.8, relevance=0.8, novelty=0.8)
    fake_event.circuit_open = False
    fake_event.fallback_reason = None
    fake_tier = TierDecision(tier="long_term", reason="score_above_threshold",
                             rule_id="T-PERSISTENT", should_persist=True)

    with patch.object(adapter, "_run_classify_and_write", return_value=classify_meta), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
         patch.object(adapter, "_conn", return_value=mock_conn), \
         patch("memory_lab.api.services.api_adapter.resolve_current_state_after_ingest", resolver_mock), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
         patch("memory_lab.api.services.api_adapter.annotate",
               return_value=MagicMock(topic_tags=[], meta_tags=[])), \
         patch("memory_lab.api.services.api_adapter.persist_body_chunks",
               return_value=MagicMock(warnings=[])):
        return adapter.create_content_minimal(
            content="plain note text", workspace_id=WS, scope_hint="should-be-visible-if-ignored",
        )


def test_low_confidence_skip_is_visible_and_resolver_not_called():
    resolver = MagicMock()
    response = _run_create(0.5, resolver)
    resolver.assert_not_called()
    assert response["current_state_status"] == "noop"
    assert response["current_state_reason"] == "low_confidence"


def test_missing_confidence_skip_is_visible():
    resolver = MagicMock()
    response = _run_create(None, resolver)
    resolver.assert_not_called()
    assert response["current_state_status"] == "noop"
    assert response["current_state_reason"] == "low_confidence"


def test_high_confidence_path_unchanged():
    from memory_lab.current_state.resolver import CurrentStateResolution

    resolver = MagicMock(return_value=CurrentStateResolution(
        status="active", reason="resolved_current_state", content_id=CONTENT,
        workspace_id=WS, memory_type="raw_memory", current_state_scope="should-be-visible-if-ignored",
        scope_source="scope_hint", anchor_id="a1", wrote=True,
    ))
    response = _run_create(0.9, resolver)
    resolver.assert_called_once()
    assert response["current_state_status"] == "active"
    assert response["current_state_scope"] == "should-be-visible-if-ignored"
