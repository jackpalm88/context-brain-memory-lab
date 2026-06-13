import os

import psycopg2
import pytest
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.public_safe]

WS1 = "00000000-0000-0000-0000-000000000421"
WS2 = "00000000-0000-0000-0000-000000000422"
SUBJECT = "00000000-0000-0000-0000-000000000423"
FORBIDDEN_FIELD_NAMES = {"answer", "verdict", "truth_decision", "resolution", "winner", "canonical_truth"}
REQUIRED = {
    "reasoning_id",
    "mode",
    "answer_candidate",
    "evidence_refs",
    "context_pack_ref",
    "traversal_steps",
    "conflict_warnings",
    "limitations",
    "provider_metadata",
    "degraded_reason",
    "non_claims",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_no_forbidden_fields(body):
    keys = set(_walk_keys(body))
    assert FORBIDDEN_FIELD_NAMES.isdisjoint(keys)
    assert "answer" not in body
    assert "answer_candidate" in body


def _db_url():
    url = os.environ.get("CB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CB_TEST_DATABASE_URL not set")
    return url


def _client(workspace_id=WS1):
    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id=SUBJECT,
            subject_type="user",
            workspace_id=workspace_id,
            role="owner",
            auth_method="test",
        )

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


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _db_url())
    with psycopg2.connect(_db_url()) as c:
        yield c
        with c.cursor() as cur:
            cur.execute("DELETE FROM content_chunks WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
            cur.execute("DELETE FROM cb_current_state_anchors WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
            cur.execute("DELETE FROM content_items WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
        c.commit()


def _insert_content(conn, *, workspace_id=WS1, content_id, text, memory_type="decision", is_current=None, supersedes=None, anchor=False):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s) ON CONFLICT (workspace_id) DO NOTHING",
            (workspace_id, f"ws-{workspace_id[-4:]}", "B14 Answer Test Workspace"),
        )
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id, memory_type, classify_confidence, current_state_scope, is_current, cs_supersedes_content_id) VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::uuid)",
            (content_id, workspace_id, memory_type, 0.9, "b14-answer", is_current, supersedes),
        )
        cur.execute(
            "INSERT INTO content_chunks (content_id, workspace_id, chunk_index, chunk_text, word_count) VALUES (%s::uuid, %s::uuid, 0, %s, %s)",
            (content_id, workspace_id, text, len(text.split())),
        )
        if anchor:
            cur.execute(
                "INSERT INTO cb_current_state_anchors (workspace_id, memory_type, scope, content_id, state_status, canonical_rank, state_reason, supersedes_content_id) VALUES (%s::uuid, %s, %s, %s::uuid, %s, %s, %s, %s::uuid)",
                (workspace_id, memory_type, "b14-answer", content_id, "active" if is_current else "superseded", 1 if is_current else 2, "test", supersedes),
            )
    conn.commit()


def _counts(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM content_items WHERE workspace_id = %s::uuid", (WS1,))
        items = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM content_chunks WHERE workspace_id = %s::uuid", (WS1,))
        chunks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM cb_current_state_anchors WHERE workspace_id = %s::uuid", (WS1,))
        anchors = cur.fetchone()[0]
    return {"items": items, "chunks": chunks, "anchors": anchors}


def test_reasoning_answer_api_deterministic_without_provider_readonly_and_shape(conn):
    _insert_content(conn, content_id="42000000-0000-0000-0000-000000000001", text="b14 answer deterministic public evidence")
    before = _counts(conn)
    req = {"query": "b14 answer deterministic", "scope": "b14-answer"}
    r1 = _client().post("/v1/reasoning/answer", json=req)
    r2 = _client().post("/v1/reasoning/answer", json=req)
    after = _counts(conn)
    assert r1.status_code == 200, r1.text
    assert r1.json() == r2.json()
    body = r1.json()
    assert set(body) == REQUIRED
    assert body["mode"] == "deterministic"
    assert body["provider_metadata"]["attempted"] is False
    assert body["provider_metadata"]["provider"] == "none"
    assert body["answer_candidate"]
    assert body["evidence_refs"]
    assert before == after
    _assert_no_forbidden_fields(body)


def test_reasoning_answer_api_conflict_warnings_limitations_and_no_provider_by_default(conn):
    _insert_content(conn, content_id="42000000-0000-0000-0000-000000000002", text="scope: b14-answer\nfinding: answer candidate uses evidence")
    _insert_content(conn, content_id="42000000-0000-0000-0000-000000000003", text="scope: b14-answer\ncounterfinding: answer candidate has conflict warning")
    r = _client().post("/v1/reasoning/answer", json={"scope": "b14-answer"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider_metadata"]["attempted"] is False
    assert body["conflict_warnings"]
    assert body["limitations"]
    assert body["non_claims"]
    _assert_no_forbidden_fields(body)


def test_reasoning_answer_api_provider_opt_in_noop_degrades_with_evidence_retained(conn):
    _insert_content(conn, content_id="42000000-0000-0000-0000-000000000004", text="b14 answer provider opt in evidence retained")
    r = _client().post("/v1/reasoning/answer", json={"query": "provider opt in", "enable_provider_synthesis": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "degraded"
    assert body["provider_metadata"]["attempted"] is True
    assert body["provider_metadata"]["provider"] == "none"
    assert body["provider_metadata"]["degraded"] is True
    assert body["degraded_reason"] == "not_configured"
    assert body["evidence_refs"]
    _assert_no_forbidden_fields(body)


def test_reasoning_answer_api_workspace_isolation_and_mismatch_guard(conn):
    _insert_content(conn, workspace_id=WS1, content_id="42000000-0000-0000-0000-000000000005", text="b14 answer isolated workspace one")
    _insert_content(conn, workspace_id=WS2, content_id="42000000-0000-0000-0000-000000000006", text="b14 answer isolated workspace two")
    ok = _client(WS1).post("/v1/reasoning/answer", json={"query": "b14 answer isolated"})
    assert ok.status_code == 200, ok.text
    ids = {ref["content_id"] for ref in ok.json()["evidence_refs"]}
    assert "42000000-0000-0000-0000-000000000005" in ids
    assert "42000000-0000-0000-0000-000000000006" not in ids
    mismatch = _client(WS1).post("/v1/reasoning/answer", json={"workspace_id": WS2, "query": "b14 answer isolated"})
    assert mismatch.status_code == 403
