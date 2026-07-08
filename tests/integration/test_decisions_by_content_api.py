"""Integration tests — CF-002 Stage 1: GET /decisions/by-content/{content_id}.

The derived content→decision reverse read, exercised through the real
create_app(): real content saves, real decision writes with declared
source_content_ids, real read over the GIN-indexed join.

ENVIRONMENT: CB_TEST_ADMIN_DSN as in test_current_state_anchors_api.py;
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
    disposable_db = f"cb_cf002_by_content_{int(time.time())}"
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


def _save_content(client, text):
    from memory_lab.ingestion.classify_pipeline import ClassificationResult

    high_conf = ClassificationResult(
        memory_type="decision", memory_sub_type="tech_choice", confidence=0.85,
        signals=["decision:"], project_topic=None, domain_hint="engineering",
    )
    with patch("memory_lab.api.services.api_adapter._classify", return_value=high_conf):
        resp = client.post("/v1/content", json={"content": text})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("persisted") is True, body
    return body["content_id"]


def _create_decision(client, title, source_content_ids):
    resp = client.post("/decisions/", json={
        "title": title,
        "decision_reason": f"reason for {title}",
        "source_content_ids": source_content_ids,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["decision_id"]


def test_source_link_readable_after_decision_create(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid = _save_content(client, "decision: adopt RabbitMQ as the message queue for async flows.")
    did = _create_decision(client, "Adopt RabbitMQ", [cid])

    resp = client.get(f"/decisions/by-content/{cid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["content_id"] == cid
    link = body["decisions"][0]
    assert link["decision_id"] == did
    assert link["link_role"] == "source"       # canonical rows arrive with Stage 2
    assert link["also_source"] is False
    assert link["decision_status"] == "active"


def test_content_in_two_decisions_newest_first(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid = _save_content(client, "decision: cap webhook retries at six attempts for all consumers.")
    _create_decision(client, "First decision", [cid])
    did2 = _create_decision(client, "Second decision", [cid])

    body = client.get(f"/decisions/by-content/{cid}").json()
    assert body["count"] == 2
    assert body["decisions"][0]["decision_id"] == did2  # created_at DESC


def test_unknown_content_returns_200_count_zero(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    resp = client.get(f"/decisions/by-content/{uuid.uuid4()}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0 and body["decisions"] == []


def test_workspace_isolation(app_env):
    ws_a = _insert_workspace(app_env)
    ws_b = _insert_workspace(app_env)
    client_a = _client(ws_a)
    client_b = _client(ws_b)
    cid = _save_content(client_a, "decision: isolate the decision join per workspace boundary.")
    _create_decision(client_a, "Isolation decision", [cid])

    assert client_a.get(f"/decisions/by-content/{cid}").json()["count"] == 1
    other = client_b.get(f"/decisions/by-content/{cid}").json()
    assert other["count"] == 0 and other["decisions"] == []


def test_gin_index_applied(app_env):
    conn = _psycopg2().connect(app_env)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'cb_decision_nodes' "
                "AND indexname = 'idx_decision_nodes_source_content_gin'"
            )
            assert cur.fetchone(), "migration 031 GIN index missing"
    finally:
        conn.close()
