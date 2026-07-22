"""Integration regression — uuid[] decision fields must round-trip as element arrays.

Bug (reported 2026-07-22 by the reference-consumer session via MCP): psycopg2
without registered UUID casters returns uuid[] columns as their raw
'{elem1,elem2}' literal string; DecisionStore._row_to_full then iterated that
string character-by-character, so GET /decisions/{id} (and MCP
explain_decision on top of it) served linked_hub_ids / source_content_ids as
exploded single-character arrays. decision_tags (text[]) was never affected —
psycopg2 parses text[] out of the box, which is why only the uuid arrays broke.

The defect lives at the driver-connection layer, so it is only catchable
against real PostgreSQL — unit tests with fake rows pass either way.

ENVIRONMENT: CB_TEST_ADMIN_DSN as in test_decisions_by_content_api.py;
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
    disposable_db = f"cb_uuid_array_roundtrip_{int(time.time())}"
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


def _assert_uuid_elements(field_name, value, expected):
    # The regression shape was ['{', 'a', '1', ...] — every element must be a
    # full UUID string, and the set must match exactly what went in.
    assert isinstance(value, list), f"{field_name}: expected list, got {type(value)}"
    for elem in value:
        uuid.UUID(elem)  # raises on single-character garbage
    assert sorted(value) == sorted(expected), f"{field_name}: {value!r} != {expected!r}"


def test_uuid_array_fields_round_trip_on_explain(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid1 = _save_content(client, "decision: pin the queue consumer prefetch at 32.")
    cid2 = _save_content(client, "decision: dead-letter after six failed deliveries.")
    hub_id = str(uuid.uuid4())

    resp = client.post("/decisions/", json={
        "title": "Queue delivery policy",
        "decision_reason": "combined prefetch + dead-letter policy",
        "source_content_ids": [cid1, cid2],
        "linked_hub_ids": [hub_id],
        "decision_tags": ["queues", "delivery"],
    })
    assert resp.status_code == 201, resp.text
    did = resp.json()["decision_id"]

    body = client.get(f"/decisions/{did}").json()
    _assert_uuid_elements("source_content_ids", body["source_content_ids"], [cid1, cid2])
    _assert_uuid_elements("linked_hub_ids", body["linked_hub_ids"], [hub_id])
    assert body["decision_tags"] == ["queues", "delivery"]


def test_uuid_array_fields_survive_status_update(app_env):
    # update_status returns RETURNING * through the same _row_to_full path.
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid = _save_content(
        client,
        "decision: retire the legacy webhook signer in favour of the v2 HMAC "
        "signer, because the legacy path cannot rotate keys without downtime "
        "and every consumer has already migrated to the v2 verification flow.",
    )

    resp = client.post("/decisions/", json={
        "title": "Retire legacy signer",
        "decision_reason": "superseded by v2 signer",
        "source_content_ids": [cid],
    })
    assert resp.status_code == 201, resp.text
    did = resp.json()["decision_id"]

    resp = client.patch(f"/decisions/{did}/status", json={"decision_status": "reversed"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision_status"] == "reversed"
    _assert_uuid_elements("source_content_ids", body["source_content_ids"], [cid])


def test_empty_uuid_arrays_stay_empty(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    resp = client.post("/decisions/", json={
        "title": "No links at all",
        "decision_reason": "standalone decision",
    })
    assert resp.status_code == 201, resp.text
    body = client.get(f"/decisions/{resp.json()['decision_id']}").json()
    assert body["source_content_ids"] == []
    assert body["linked_hub_ids"] == []
