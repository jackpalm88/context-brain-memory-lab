"""Integration tests — Patch 1: GET /v1/content/{content_id}/canonical-body.

Exercised through the real create_app(): real content saves through the real
write path (create_content_minimal -> content_chunks), real reconstruction
via memory_lab.content.canonical_body, real read over the live schema.

Decision 5533831e-c751-434a-8ae7-f8f40cdaf0f8: canonical body is verified
reconstruction, not a direct storage read (content_items carries no raw body
column). This suite proves the end-to-end contract: hash-verified for
recoverable content, fail-closed (never a wrong body, never a 5xx) otherwise.

ENVIRONMENT: CB_TEST_ADMIN_DSN as in test_decisions_by_content_api.py; tests
skip with SKIPPED_NO_PUBLIC_STYLE_TEST_DSN when unset.
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
    disposable_db = f"cb_canonical_body_{int(time.time())}"
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
            auth_subject_id="00000000-0000-0000-0000-000000000202",
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


def test_single_chunk_content_is_hash_verified(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    text = "decision: adopt a single canonical read path for exact body recovery."
    cid = _save_content(client, text)

    resp = client.get(f"/v1/content/{cid}/canonical-body")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_id"] == cid
    assert body["workspace_id"] == ws_id
    assert body["fidelity"] == "hash-verified"
    assert body["body"] == text
    assert body["body_sha256"]
    assert body["hash_semantics"]


def test_multi_chunk_content_is_hash_verified(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    paragraph = (
        "Deterministic chunking must remain stable across releases so that "
        "verified reconstruction keeps working for the existing corpus. "
    )
    text = "decision: " + "\n\n".join(f"Paragraph {i}. {paragraph * 3}" for i in range(12))
    cid = _save_content(client, text)

    resp = client.get(f"/v1/content/{cid}/canonical-body")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fidelity"] == "hash-verified"
    assert body["body"] == text


def test_unknown_content_id_is_404(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    resp = client.get(f"/v1/content/{uuid.uuid4()}/canonical-body")
    assert resp.status_code == 404


def test_workspace_isolation_is_404_not_cross_tenant_read(app_env):
    ws_a = _insert_workspace(app_env)
    ws_b = _insert_workspace(app_env)
    client_a = _client(ws_a)
    client_b = _client(ws_b)
    cid = _save_content(client_a, "decision: keep canonical-body reads workspace-scoped.")

    resp = client_b.get(f"/v1/content/{cid}/canonical-body")
    assert resp.status_code == 404


def test_missing_chunk_fails_closed_not_500(app_env):
    # Directly corrupt persisted chunks (delete chunk_index 0) to prove the
    # endpoint fails closed to unverifiable rather than 500ing or guessing.
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    text = "decision: fail closed instead of guessing when chunk evidence is broken."
    cid = _save_content(client, text)

    conn = _psycopg2().connect(app_env)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM content_chunks WHERE content_id = %s::uuid", (cid,))
        conn.commit()
    finally:
        conn.close()

    resp = client.get(f"/v1/content/{cid}/canonical-body")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fidelity"] == "unavailable"
    assert body["body"] is None
    assert body["body_sha256"] is None


def test_expected_version_match_returns_body_normally(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    text = "decision: expected_version happy path proceeds exactly as without it."
    cid = _save_content(client, text)
    body_sha256 = client.get(f"/v1/content/{cid}/canonical-body").json()["body_sha256"]

    resp = client.get(f"/v1/content/{cid}/canonical-body?expected_version={body_sha256}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fidelity"] == "hash-verified"
    assert body["body"] == text
    assert "version_conflict" not in body


def test_expected_version_mismatch_is_409_without_reconstruction(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid = _save_content(client, "decision: expected_version mismatch fails closed with 409.")

    resp = client.get(f"/v1/content/{cid}/canonical-body?expected_version=not-the-real-hash")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["detail"] == "mismatch"
    assert detail["expected_version"] == "not-the-real-hash"
    assert detail["current_version"]  # the real stored content_hash


def test_expected_version_unknown_when_no_stored_hash(app_env):
    # A row with content_hash=NULL and no chunks (unavailable) but a caller
    # supplies expected_version anyway -- must fail closed to version_unknown,
    # never silently proceed as if there were nothing to check.
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid = _save_content(client, "decision: version_unknown when content_hash is null.")

    conn = _psycopg2().connect(app_env)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE content_items SET content_hash = NULL WHERE content_id = %s::uuid", (cid,))
        conn.commit()
    finally:
        conn.close()

    resp = client.get(f"/v1/content/{cid}/canonical-body?expected_version=anything")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["detail"] == "version_unknown"


def test_empty_expected_version_is_422(app_env):
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    cid = _save_content(client, "decision: empty expected_version query value is a stated-contract violation.")

    resp = client.get(f"/v1/content/{cid}/canonical-body?expected_version=")

    assert resp.status_code == 422
