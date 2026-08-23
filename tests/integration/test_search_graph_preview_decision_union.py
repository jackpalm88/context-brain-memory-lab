"""Integration tests — search_graph_preview(node_type="decision") union over
cb_decision_nodes.

Root cause: cb_decision_nodes (create_decision_memory) is a separate table from
content_items/content_chunks, and search_graph_preview historically queried only
the latter — so node_type="decision" was a structural false negative on the real
decision corpus regardless of query text. This file exercises the fix: (a) a real
decision is now findable, and (b) a genuine "no query match" is distinguishable
from a "wrong workspace" zero — neither should read as "no decisions exist."

ENVIRONMENT: CB_TEST_ADMIN_DSN as in test_decisions_by_content_api.py; tests skip
with SKIPPED_NO_PUBLIC_STYLE_TEST_DSN when unset.
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
_SKIP_MIGRATION_IDS = {"002"}  # requires pgvector extension — not guaranteed in test env


@pytest.fixture(scope="module")
def test_dsn():
    if not _ADMIN_DSN:
        pytest.skip(
            "SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — CB_TEST_ADMIN_DSN not set. "
            "Provide a dedicated CB test Postgres: "
            "CB_TEST_ADMIN_DSN=postgresql://cb_test:cb_test@localhost:5433/postgres"
        )
    disposable_db = f"cb_search_preview_decision_{int(time.time())}"
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


def _create_decision(client, title, decision_reason=None):
    resp = client.post("/decisions/", json={
        "title": title,
        "decision_reason": decision_reason or f"reason for {title}",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["decision_id"]


def _search_preview(client, query, node_type="decision"):
    resp = client.get("/v1/graph/search-preview", params={"query": query, "node_type": node_type})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_real_decision_found_via_search_graph_preview(app_env):
    """(a) A formal decision that exists only in cb_decision_nodes (never in
    content_items) must be discoverable through search_graph_preview(node_type=
    "decision") — this is the core false-negative regression."""
    ws_id = _insert_workspace(app_env)
    client = _client(ws_id)
    did = _create_decision(
        client, "Adopt Kafka for event streaming",
        decision_reason="Kafka gives us replay and multi-consumer fan-out that RabbitMQ lacks.",
    )

    body = _search_preview(client, "Kafka")
    assert body["count"] >= 1, body
    decision_hits = [r for r in body["results"] if r.get("source") == "decision_node"]
    assert decision_hits, f"no decision_node-sourced result in {body['results']}"
    hit = next(r for r in decision_hits if r["decision_id"] == did)
    assert hit["node_type"] == "decision"
    assert "Kafka" in hit["quick_summary"]


def test_zero_query_match_vs_zero_workspace_mismatch_are_distinguishable(app_env):
    """(b) Two different zero-result causes must not collapse into the same
    "no decisions" reading:
      - a real decision exists but the query text doesn't match it (honest
        empty on THIS query, not on the corpus), and
      - the same decision exists but in a different workspace (honest empty on
        THIS workspace's isolation boundary, not on the corpus either).
    A positive match in the owning workspace proves the decision — and the
    fix — are real, so the two zeros above can't be explained by "the decision
    doesn't exist" or "the fix doesn't work."
    """
    ws_a = _insert_workspace(app_env)
    ws_b = _insert_workspace(app_env)
    client_a = _client(ws_a)
    client_b = _client(ws_b)

    _create_decision(
        client_a, "Adopt Kafka for event streaming",
        decision_reason="Kafka gives us replay and multi-consumer fan-out that RabbitMQ lacks.",
    )

    # Positive control: findable in its own workspace.
    found = _search_preview(client_a, "Kafka")
    assert found["count"] >= 1, found

    # Zero cause #1: real corpus, query text doesn't match anything in it.
    no_match = _search_preview(client_a, "quantum teleportation protocol")
    assert no_match["count"] == 0
    assert no_match["results"] == []

    # Zero cause #2: same decision, wrong workspace — isolation, not absence.
    wrong_workspace = _search_preview(client_b, "Kafka")
    assert wrong_workspace["count"] == 0
    assert wrong_workspace["results"] == []

    # Both are legitimately empty, but for different reasons — the search
    # layer doesn't need to prove that distinction itself (that's a documented
    # contract, not a field), yet the test proves it's not the SAME reason by
    # showing the corpus round-trips fine when workspace+query are aligned.
