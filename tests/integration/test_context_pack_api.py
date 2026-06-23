import os

import pytest


def _psycopg2():
    return pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary to run DB integration tests.",
    )


pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.public_safe]

WS1 = "00000000-0000-0000-0000-000000000301"
WS2 = "00000000-0000-0000-0000-000000000302"
SUBJECT = "00000000-0000-0000-0000-000000000303"


def _db_url():
    url = os.environ.get("CB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CB_TEST_DATABASE_URL not set")
    return url


def _client(workspace_id=WS1):
    _psycopg2()
    from fastapi.testclient import TestClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.dependencies.auth import require_permission
    from memory_lab.api.main import create_app

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
    with _psycopg2().connect(_db_url()) as c:
        yield c
        c.rollback()
        with c.cursor() as cur:
            cur.execute("DELETE FROM content_chunks WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
            cur.execute("DELETE FROM cb_current_state_anchors WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
            cur.execute("DELETE FROM content_items WHERE workspace_id IN (%s::uuid, %s::uuid)", (WS1, WS2))
        c.commit()


def _insert_content(
    conn,
    *,
    workspace_id=WS1,
    content_id,
    text,
    memory_type="decision",
    classify_confidence=0.9,
    scope="b12-context-pack",
    is_current=None,
    supersedes=None,
    anchor=False,
):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s) ON CONFLICT (workspace_id) DO NOTHING",
            (workspace_id, f"ws-{workspace_id[-4:]}", "B12 Test Workspace"),
        )
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id, memory_type, classify_confidence, current_state_scope, is_current, cs_supersedes_content_id) VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::uuid)",
            (content_id, workspace_id, memory_type, classify_confidence, scope, is_current, supersedes),
        )
        cur.execute(
            "INSERT INTO content_chunks (content_id, workspace_id, chunk_index, chunk_text, word_count) VALUES (%s::uuid, %s::uuid, 0, %s, %s)",
            (content_id, workspace_id, text, len(text.split())),
        )
        if anchor:
            cur.execute(
                "INSERT INTO cb_current_state_anchors (workspace_id, memory_type, scope, content_id, state_status, canonical_rank, state_reason, supersedes_content_id) VALUES (%s::uuid, %s, %s, %s::uuid, %s, %s, %s, %s::uuid)",
                (workspace_id, memory_type, scope, content_id, "active" if is_current else "superseded", 1 if is_current else 2, "test", supersedes),
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


def test_context_pack_api_result_shape(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000001", text="b12 context pack supporting evidence")
    r = _client().post("/v1/context-packs/build", json={"query": "b12 context pack", "limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    for key in [
        "context_pack_id", "workspace_id", "query", "scope", "summary_metadata", "supporting_evidence",
        "current_state_signals", "conflict_candidates", "counterfindings", "stale_or_superseded_items",
        "omitted_items", "warnings", "non_claims",
    ]:
        assert key in body
    assert body["context_pack_id"].startswith("cp_")
    assert body["summary_metadata"]["truth_arbitration"] is False
    assert body["summary_metadata"]["provider_backed_reasoning"] is False


def test_support_only_pack(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000002", text="b12 support only unique evidence")
    body = _client().post("/v1/context-packs/build", json={"query": "support only unique", "include_conflicts": False}).json()
    assert body["supporting_evidence"]
    assert body["conflict_candidates"] == []
    assert "answer" not in body


def test_pack_with_current_state_signal(conn):
    old = "30000000-0000-0000-0000-000000000003"
    new = "30000000-0000-0000-0000-000000000004"
    _insert_content(conn, content_id=new, text="b12 current state new", is_current=True, anchor=True)
    _insert_content(conn, content_id=old, text="b12 current state old", is_current=False, supersedes=new, anchor=True)
    body = _client().post("/v1/context-packs/build", json={"scope": "b12-context-pack", "query": "current state"}).json()
    assert any(e["content_id"] == new for e in body["current_state_signals"])
    assert any(e["content_id"] == old for e in body["stale_or_superseded_items"])


def test_pack_with_conflict_counterfinding_candidate(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000005", text="scope: b12-context-pack\nfinding: context pack is evidence container")
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000006", text="scope: b12-context-pack\ncounterfinding: hidden ask endpoint risk")
    body = _client().post("/v1/context-packs/build", json={"scope": "b12-context-pack"}).json()
    assert any(c["conflict_type"] == "explicit_counterfinding" for c in body["conflict_candidates"])
    assert body["counterfindings"]


def test_memory_type_filter_respected(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000007", text="b12 filter decision evidence", memory_type="decision")
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000008", text="b12 filter raw evidence", memory_type="raw_memory")
    body = _client().post("/v1/context-packs/build", json={"query": "b12 filter", "memory_type": "decision"}).json()
    assert body["supporting_evidence"]
    assert {e["memory_type"] for e in body["supporting_evidence"]} == {"decision"}


def test_workspace_isolation(conn):
    _insert_content(conn, workspace_id=WS1, content_id="30000000-0000-0000-0000-000000000009", text="b12 isolated workspace one")
    _insert_content(conn, workspace_id=WS2, content_id="30000000-0000-0000-0000-000000000010", text="b12 isolated workspace two")
    body = _client(WS1).post("/v1/context-packs/build", json={"query": "b12 isolated"}).json()
    ids = {e["content_id"] for e in body["supporting_evidence"]}
    assert "30000000-0000-0000-0000-000000000009" in ids
    assert "30000000-0000-0000-0000-000000000010" not in ids
    mismatch = _client(WS1).post("/v1/context-packs/build", json={"workspace_id": WS2, "query": "b12 isolated"})
    assert mismatch.status_code == 403


def test_discard_no_persist_ignored(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000011", text="b12 persisted visible evidence")
    body = _client().post("/v1/context-packs/build", json={"query": "discarded transient unsaved"}).json()
    assert body["supporting_evidence"] == []


def test_deterministic_context_pack_id_and_ordering(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000012", text="b12 deterministic alpha")
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000013", text="b12 deterministic alpha beta")
    req = {"query": "b12 deterministic", "memory_types": ["decision"]}
    body1 = _client().post("/v1/context-packs/build", json=req).json()
    body2 = _client().post("/v1/context-packs/build", json=req).json()
    assert body1["context_pack_id"] == body2["context_pack_id"]
    assert body1["supporting_evidence"] == body2["supporting_evidence"]


def test_no_provider_calls_and_no_db_mutation(conn, monkeypatch):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000014", text="b12 readonly mutation probe", is_current=True, anchor=True)
    before = _counts(conn)
    body = _client().post("/v1/context-packs/build", json={"query": "readonly mutation probe"}).json()
    after = _counts(conn)
    assert body["summary_metadata"]["db_mutation"] is False
    assert before == after


def test_retrieval_search_unchanged(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000015", text="b12 retrieval unchanged")
    r = _client().post("/v1/retrieval/search", json={"query": "retrieval unchanged"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body
    assert "context_pack_id" not in body
    assert body["mode"] == "workspace_scoped_deterministic_db"


def test_conflicts_search_unchanged(conn):
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000016", text="scope: b12-context-pack\nfinding: unchanged")
    _insert_content(conn, content_id="30000000-0000-0000-0000-000000000017", text="scope: b12-context-pack\ncontradicts: unchanged")
    r = _client().post("/v1/conflicts/search", json={"scope": "b12-context-pack"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "conflicts" in body
    assert "context_pack_id" not in body
    assert body["truth_arbitration"] is False
