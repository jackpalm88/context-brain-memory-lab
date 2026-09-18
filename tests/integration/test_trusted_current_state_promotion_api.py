"""Integration tests for the trusted current-state promotion seam.

This is the narrow authority path that exposes explicit state_identity promotion
without weakening the general /v1/content route.
"""
import glob
import os
import time
import uuid
from urllib.parse import urlparse, urlunparse

import pytest


def _psycopg2():
    module = pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary to run DB integration tests.",
    )
    __import__("psycopg2.extensions")
    return module


pytestmark = [pytest.mark.integration, pytest.mark.public_safe, pytest.mark.provider_optional]

_ADMIN_DSN = os.environ.get("CB_TEST_ADMIN_DSN", "").strip()
_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "migrations")
_SKIP_MIGRATION_IDS = {"002"}


@pytest.fixture(scope="module")
def test_dsn():
    if not _ADMIN_DSN:
        pytest.skip("SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — CB_TEST_ADMIN_DSN not set")
    disposable_db = f"cb_trusted_promotion_{int(time.time())}"
    admin_conn = _psycopg2().connect(_ADMIN_DSN)
    admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    with admin_conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{disposable_db}";')
    admin_conn.close()

    parts = urlparse(_ADMIN_DSN)
    db_dsn = urlunparse(parts._replace(path=f"/{disposable_db}"))
    db_conn = _psycopg2().connect(db_dsn)
    db_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        for mig_path in sorted(glob.glob(os.path.join(_MIGRATIONS_DIR, "*.sql"))):
            migration_id = os.path.basename(mig_path).split("_")[0]
            if migration_id in _SKIP_MIGRATION_IDS:
                continue
            with open(mig_path) as fh:
                sql = fh.read()
            if migration_id == "000":
                sql = sql.replace("CREATE EXTENSION IF NOT EXISTS vector;", "-- pgvector stripped")
            with db_conn.cursor() as cur:
                cur.execute(sql)
    except Exception:
        _drop_db(disposable_db)
        raise
    finally:
        db_conn.close()
    yield db_dsn
    _drop_db(disposable_db)


def _drop_db(db_name):
    try:
        admin_conn = _psycopg2().connect(_ADMIN_DSN)
        admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with admin_conn.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid();", (db_name,))
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
        admin_conn.close()
    except Exception:
        pass


@pytest.fixture()
def app_env(test_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_dsn)
    yield test_dsn


def _insert_workspace(test_dsn) -> str:
    ws_id = str(uuid.uuid4())
    conn = _psycopg2().connect(test_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s)",
                (ws_id, f"test-{ws_id[:8]}", "Test Workspace"),
            )
        conn.commit()
    finally:
        conn.close()
    return ws_id


def _client(workspace_id, role="service_agent"):
    from fastapi.testclient import TestClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.main import create_app

    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id="00000000-0000-0000-0000-000000000301",
            subject_type="service_agent" if role == "service_agent" else "human",
            workspace_id=workspace_id,
            role=role,
            auth_method="test",
        )

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency":
                app.dependency_overrides[call] = override
    return TestClient(app)


def _promote(client, *, content, state_identity, quick_summary=None):
    payload = {
        "content": content,
        "memory_type": "decision",
        "state_identity": state_identity,
        "scope_hint": "trusted-promotion-disposable-scope",
    }
    if quick_summary:
        payload["quick_summary"] = quick_summary
    resp = client.post("/v1/current-state/promote", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_trusted_promote_create_supersede_rollback_readback(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id, role="service_agent")
    state_identity = f"trusted-promotion-{uuid.uuid4()}"

    v1 = _promote(
        client,
        content="decision: trusted disposable state is v1. Rationale: first canonical current-state proof write.",
        state_identity=state_identity,
        quick_summary="v1 disposable state",
    )
    assert v1["content_id"]
    assert v1["previous_anchor_id"] is None
    assert v1["current_anchor"]["content_id"] == v1["content_id"]
    assert v1["current_anchor"]["state_identity"] == state_identity
    assert len(v1["supersession_chain"]) == 1

    v2 = _promote(
        client,
        content="decision: trusted disposable state is v2. Rationale: second write supersedes v1 for the same explicit identity.",
        state_identity=state_identity,
        quick_summary="v2 disposable state",
    )
    assert v2["previous_anchor_id"] == v1["current_anchor"]["anchor_id"]
    assert v2["current_anchor"]["content_id"] == v2["content_id"]
    assert v2["current_anchor"]["supersedes_content_id"] == v1["content_id"]
    assert [row["state_status"] for row in v2["supersession_chain"]] == ["superseded", "active"]

    rollback = _promote(
        client,
        content="decision: trusted disposable state is restored to v1 semantics. Rationale: rollback is a new trusted write, not hidden mutation.",
        state_identity=state_identity,
        quick_summary="v1 semantics restored",
    )
    assert rollback["previous_anchor_id"] == v2["current_anchor"]["anchor_id"]
    assert rollback["current_anchor"]["content_id"] == rollback["content_id"]
    assert rollback["current_anchor"]["supersedes_content_id"] == v2["content_id"]
    assert [row["state_status"] for row in rollback["supersession_chain"]] == ["superseded", "superseded", "active"]

    anchors = client.get(
        "/v1/current-state/anchors",
        params={
            "scope": "trusted-promotion-disposable-scope",
            "memory_type": "decision",
            "state_identity": state_identity,
        },
    )
    assert anchors.status_code == 200, anchors.text
    body = anchors.json()
    assert body["count"] == 1
    assert body["anchors"][0]["content_id"] == rollback["content_id"]
    assert body["anchors"][0]["quick_summary"] == "v1 semantics restored"

    old = client.get(f"/v1/content/{v1['content_id']}").json()
    current = client.get(f"/v1/content/{rollback['content_id']}").json()
    assert old["is_current"] is False
    assert current["is_current"] is True


def test_general_content_route_still_rejects_state_identity(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id, role="service_agent")

    resp = client.post(
        "/v1/content",
        json={
            "content": "decision: untrusted general write must not accept canonical state identity.",
            "scope_hint": "general-content-no-state-identity",
            "state_identity": "must-not-be-accepted",
        },
    )
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved.get("persisted") is True
    assert "state_identity" not in saved
    anchors = client.get("/v1/current-state/anchors", params={"scope": "general-content-no-state-identity"})
    assert anchors.status_code == 200
    assert anchors.json()["count"] == 0


def _force_low_transient_score(monkeypatch):
    """Force content scoring into the persisted-but-transient band."""
    from types import SimpleNamespace
    import memory_lab.api.services.api_adapter as api_adapter

    event = SimpleNamespace(
        scores=SimpleNamespace(quality=0.45, relevance=0.5, novelty=0.55, composite=0.4975),
        circuit_open=False,
        fallback_reason="",
    )
    monkeypatch.setattr(api_adapter, "score_content", lambda content: event)


def test_trusted_promotion_forces_authoritative_tier_even_when_composite_is_transient(app_env, monkeypatch):
    ws_id = _insert_workspace(app_env)
    _force_low_transient_score(monkeypatch)
    client = _client(ws_id, role="service_agent")
    state_identity = f"trusted-tier-force-{uuid.uuid4()}"

    promoted = _promote(
        client,
        content="low signal but explicitly trusted canonical promotion",
        state_identity=state_identity,
        quick_summary="trusted tier force proof",
    )

    assert promoted["mode"] == "trusted_current_state_promotion"
    assert promoted["trusted_current_state_promotion"] is True
    assert promoted["tier"] == "persistent"
    assert promoted["tier_reason"].startswith("trusted_current_state_promotion:")
    assert promoted["current_anchor"]["content_id"] == promoted["content_id"]

    saved = client.get(f"/v1/content/{promoted['content_id']}").json()
    assert saved["is_current"] is True
    assert saved["tier"] == "persistent"


def test_general_content_route_keeps_normal_transient_scoring(app_env, monkeypatch):
    ws_id = _insert_workspace(app_env)
    _force_low_transient_score(monkeypatch)
    client = _client(ws_id, role="service_agent")

    resp = client.post(
        "/v1/content",
        json={
            "content": "low signal ordinary governed write should remain transient",
            "scope_hint": "general-content-transient-scoring",
        },
    )
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["persisted"] is True
    assert saved["mode"] == "governed"
    assert saved["tier"] == "transient"
    assert saved["tier_reason"].startswith("composite_transient_range:")

