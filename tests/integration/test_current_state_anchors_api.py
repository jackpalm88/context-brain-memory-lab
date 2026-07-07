"""Integration tests — CF-003: GET /v1/current-state/anchors through the real app.

The endpoint is the forward pointer of the supersession chain: given a scope,
return its ACTIVE anchor(s). Exercised end-to-end: real create_app(), real
ingest writes (resolver populates cb_current_state_anchors), real read.

ENVIRONMENT: CB_TEST_ADMIN_DSN as in test_classify_ingest_wiring_integration.py;
tests skip with SKIPPED_NO_PUBLIC_STYLE_TEST_DSN when unset.
"""
import glob
import os
import time
import uuid
from unittest.mock import patch
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
_SKIP_MIGRATION_IDS = {"002"}  # requires pgvector extension — not guaranteed in test env


@pytest.fixture(scope="module")
def test_dsn():
    if not _ADMIN_DSN:
        pytest.skip(
            "SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — CB_TEST_ADMIN_DSN not set. "
            "Provide a dedicated CB test Postgres: "
            "CB_TEST_ADMIN_DSN=postgresql://cb_test:cb_test@localhost:5433/postgres"
        )
    disposable_db = f"cb_cf003_anchors_{int(time.time())}"
    try:
        admin_conn = _psycopg2().connect(_ADMIN_DSN)
        admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with admin_conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{disposable_db}";')
        admin_conn.close()
    except Exception as exc:
        pytest.skip(f"SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — could not connect to CB_TEST_ADMIN_DSN: {exc}")

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
                sql = sql.replace(
                    "CREATE EXTENSION IF NOT EXISTS vector;",
                    "-- pgvector stripped for CB test env",
                )
            with db_conn.cursor() as cur:
                cur.execute(sql)
    except Exception as exc:
        db_conn.close()
        _drop_disposable_db(disposable_db)
        pytest.skip(f"SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — migration apply failed: {exc}")
    finally:
        db_conn.close()

    yield db_dsn

    _drop_disposable_db(disposable_db)


def _drop_disposable_db(db_name: str) -> None:
    try:
        admin_conn = _psycopg2().connect(_ADMIN_DSN)
        admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid();",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
        admin_conn.close()
    except Exception:
        pass  # best-effort


@pytest.fixture()
def app_env(test_dsn):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_dsn
    yield test_dsn
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


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


def _client(workspace_id):
    """Real create_app() with every require_permission closure overridden — the
    endpoint under test must be reached through the actual app wiring."""
    from fastapi.testclient import TestClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.main import create_app

    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id="00000000-0000-0000-0000-000000000201",
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
            if getattr(call, "__name__", "") == "_dependency":
                app.dependency_overrides[call] = override
    return TestClient(app)


def _high_confidence_decision():
    from memory_lab.ingestion.classify_pipeline import ClassificationResult

    return ClassificationResult(
        memory_type="decision", memory_sub_type="tech_choice", confidence=0.85,
        signals=["decision:"], project_topic=None, domain_hint="engineering",
    )


def _save(client, text, scope_hint):
    with patch(
        "memory_lab.api.services.api_adapter._classify",
        return_value=_high_confidence_decision(),
    ):
        resp = client.post("/v1/content", json={"content": text, "scope_hint": scope_hint})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("persisted") is True, body
    return body


def test_anchor_read_returns_successor_of_superseded_item(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)

    first = _save(client, "decision: adopt Kafka as the message queue for all async flows.",
                  "message-queue")
    second = _save(client, "decision: switch from Kafka to RabbitMQ as the message queue.",
                   "message-queue")

    resp = client.get("/v1/current-state/anchors", params={"scope": "message-queue"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "message-queue"
    assert body["workspace_id"] == ws_id
    assert body["count"] == 1
    anchor = body["anchors"][0]
    assert anchor["content_id"] == second["content_id"]
    assert anchor["supersedes_content_id"] == first["content_id"]
    assert anchor["state_status"] == "active"
    assert anchor["memory_type"] == "decision"
    assert anchor["is_current"] is True

    # the CF-003 loop: a superseded item's scope now resolves forward
    old = client.get(f"/v1/content/{first['content_id']}").json()
    assert old["is_current"] is False
    forward = client.get("/v1/current-state/anchors",
                         params={"scope": old["current_state_scope"]}).json()
    assert forward["anchors"][0]["content_id"] == second["content_id"]


def test_scope_is_normalized_like_the_write_path(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    saved = _save(client, "decision: use Redis for the session cache layer.", "session cache")

    resp = client.get("/v1/current-state/anchors", params={"scope": "Session Cache!"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "session-cache"
    assert body["count"] == 1
    assert body["anchors"][0]["content_id"] == saved["content_id"]


def test_memory_type_filter_and_vocabulary(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    _save(client, "decision: cap webhook retries at six attempts.", "webhook-retries")

    hit = client.get("/v1/current-state/anchors",
                     params={"scope": "webhook-retries", "memory_type": "decision"}).json()
    assert hit["count"] == 1
    miss = client.get("/v1/current-state/anchors",
                      params={"scope": "webhook-retries", "memory_type": "milestone"}).json()
    assert miss["count"] == 0 and miss["anchors"] == []

    bad = client.get("/v1/current-state/anchors",
                     params={"scope": "webhook-retries", "memory_type": "bogus"})
    assert bad.status_code == 422
    assert "memory_type" in bad.json()["detail"]


def test_workspace_isolation_and_unclaimed_scope(app_env):
    ws_a = _insert_workspace(app_env)
    ws_b = _insert_workspace(app_env)
    client_a = _client(ws_a)
    client_b = _client(ws_b)
    _save(client_a, "decision: isolate anchors per workspace boundary.", "isolation-check")

    own = client_a.get("/v1/current-state/anchors", params={"scope": "isolation-check"}).json()
    assert own["count"] == 1
    other = client_b.get("/v1/current-state/anchors", params={"scope": "isolation-check"}).json()
    assert other["count"] == 0 and other["anchors"] == []

    unclaimed = client_a.get("/v1/current-state/anchors", params={"scope": "never-written"}).json()
    assert unclaimed["count"] == 0 and unclaimed["anchors"] == []

    missing = client_a.get("/v1/current-state/anchors")
    assert missing.status_code == 422
