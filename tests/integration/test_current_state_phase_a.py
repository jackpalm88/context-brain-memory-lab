"""Integration tests — current-state Phase A (decision 4a11008b): split
current_state_scope (grouping) from state_identity (replacement identity).

Maps directly to the 9-item acceptance matrix ratified in
engineering/current-state-phase-a-implementation-spec-2026-08-23.md §9
(review de24fac8-a7c5-435f-883a-b0350230a1f1). Each test function is labeled
with the matrix item(s) it covers.

ENVIRONMENT: CB_TEST_ADMIN_DSN as in test_search_graph_preview_decision_union.py;
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
    disposable_db = f"cb_current_state_phase_a_{int(time.time())}"
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
def conn(test_dsn):
    connection = _psycopg2().connect(test_dsn)
    yield connection
    connection.close()


def _insert_workspace(conn) -> str:
    ws_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s)",
            (ws_id, f"test-{ws_id[:8]}", "Test Workspace"),
        )
    conn.commit()
    return ws_id


def _high_conf(memory_type="decision", **kwargs):
    from memory_lab.ingestion.classify_pipeline import ClassificationResult

    return ClassificationResult(
        memory_type=memory_type, memory_sub_type=kwargs.get("memory_sub_type", "tech_choice"),
        confidence=0.85, signals=["decision:"],
        project_topic=kwargs.get("project_topic"), domain_hint=kwargs.get("domain_hint", "engineering"),
    )


def _real_dict_cursor():
    from psycopg2.extras import RealDictCursor

    return RealDictCursor


def _anchor_row(conn, workspace_id, content_id):
    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT * FROM cb_current_state_anchors WHERE workspace_id = %s::uuid AND content_id = %s::uuid",
            (workspace_id, content_id),
        )
        return cur.fetchone()


def _content_row(conn, content_id):
    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT is_current, current_state_scope, state_identity, cs_supersedes_content_id "
            "FROM content_items WHERE content_id = %s::uuid",
            (content_id,),
        )
        return cur.fetchone()


def test_no_state_identity_never_supersedes(test_dsn, conn):
    """Acceptance #1: no state_identity -> grouping works, supersession never fires."""
    from memory_lab.api.services.api_adapter import ApiAdapter

    ws_id = _insert_workspace(conn)
    adapter = ApiAdapter(test_dsn)

    with patch("memory_lab.api.services.api_adapter._classify", return_value=_high_conf()):
        first = adapter.create_content_minimal(content="alpha bravo charlie no identity one", workspace_id=ws_id)
        second = adapter.create_content_minimal(content="alpha bravo charlie no identity two", workspace_id=ws_id)

    assert first["created"] and second["created"]
    for cid in (first["content_id"], second["content_id"]):
        assert _anchor_row(conn, ws_id, cid) is None, "no anchor should ever be written without state_identity"
        row = _content_row(conn, cid)
        assert row["cs_supersedes_content_id"] is None
        assert row["state_identity"] is None
        assert row["current_state_scope"] is not None  # grouping still works


def test_trusted_identity_supersedes_exact_triple_only(test_dsn, conn):
    """Acceptance #2 + #9 (true-supersession fixture equivalent): trusted caller +
    state_identity supersedes only an identical (workspace, memory_type, state_identity)."""
    from memory_lab.api.services.api_adapter import ApiAdapter

    ws_id = _insert_workspace(conn)
    adapter = ApiAdapter(test_dsn)

    with patch("memory_lab.api.services.api_adapter._classify", return_value=_high_conf()):
        a = adapter.create_content_minimal(
            content="decision: use Kafka for the message queue",
            workspace_id=ws_id, state_identity="message-queue-choice", state_identity_trusted=True,
        )
        b = adapter.create_content_minimal(
            content="decision: switch the message queue to RabbitMQ",
            workspace_id=ws_id, state_identity="message-queue-choice", state_identity_trusted=True,
        )

    a_row = _content_row(conn, a["content_id"])
    b_row = _content_row(conn, b["content_id"])
    assert a_row["is_current"] is False
    assert b_row["is_current"] is True
    assert b_row["cs_supersedes_content_id"] == a["content_id"]
    assert b_row["state_identity"] == "message-queue-choice"

    b_anchor = _anchor_row(conn, ws_id, b["content_id"])
    assert b_anchor["state_status"] == "active"
    assert b_anchor["state_identity"] == "message-queue-choice"


def test_same_scope_different_identity_both_active_no_conflict(test_dsn, conn):
    """Acceptance #3 + #5: same current_state_scope, different state_identity ->
    both stay active, and the conflict detector raises no multiple_current_anchors_v1
    candidate for them."""
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.conflicts.detector import ConflictSourceRow, detect_conflict_candidates

    ws_id = _insert_workspace(conn)
    adapter = ApiAdapter(test_dsn)

    with patch("memory_lab.api.services.api_adapter._classify", return_value=_high_conf()):
        x = adapter.create_content_minimal(
            content="decision: adopt Kafka for retrieval-embeddings pipeline routing",
            workspace_id=ws_id, scope_hint="retrieval-embeddings-shared-scope",
            state_identity="pipeline-x", state_identity_trusted=True,
        )
        y = adapter.create_content_minimal(
            content="decision: adopt pgvector for retrieval-embeddings similarity search",
            workspace_id=ws_id, scope_hint="retrieval-embeddings-shared-scope",
            state_identity="pipeline-y", state_identity_trusted=True,
        )

    x_row = _content_row(conn, x["content_id"])
    y_row = _content_row(conn, y["content_id"])
    assert x_row["is_current"] is True
    assert y_row["is_current"] is True
    assert x_row["current_state_scope"] == y_row["current_state_scope"]
    assert x_row["state_identity"] != y_row["state_identity"]

    rows = [
        ConflictSourceRow(
            content_id=x["content_id"], workspace_id=ws_id, text="Kafka retrieval-embeddings pipeline routing",
            memory_type="decision", classify_confidence=0.85, is_current=True,
            current_state_scope=x_row["current_state_scope"], state_identity=x_row["state_identity"],
        ),
        ConflictSourceRow(
            content_id=y["content_id"], workspace_id=ws_id, text="pgvector retrieval-embeddings similarity search",
            memory_type="decision", classify_confidence=0.85, is_current=True,
            current_state_scope=y_row["current_state_scope"], state_identity=y_row["state_identity"],
        ),
    ]
    candidates = detect_conflict_candidates(rows, workspace_id=ws_id)
    multi_anchor_hits = [c for c in candidates if c.detection_rule == "multiple_current_anchors_v1"]
    assert multi_anchor_hits == [], f"legitimate multi-identity coexistence must not be flagged: {multi_anchor_hits}"


def test_untrusted_caller_state_identity_rejected(test_dsn, conn):
    """Acceptance #4: caller supplies state_identity without asserting trust -> fails
    explicitly, never silently accepted or silently dropped."""
    from memory_lab.api.services.api_adapter import ApiAdapter

    ws_id = _insert_workspace(conn)
    adapter = ApiAdapter(test_dsn)

    with pytest.raises(ValueError, match="state_identity_trusted"):
        adapter.create_content_minimal(
            content="an untrusted caller tries to declare a state identity",
            workspace_id=ws_id, state_identity="sneaky-identity",
        )
    # state_identity_trusted explicitly False must behave the same as omitted.
    with pytest.raises(ValueError, match="state_identity_trusted"):
        adapter.create_content_minimal(
            content="an untrusted caller tries to declare a state identity again",
            workspace_id=ws_id, state_identity="sneaky-identity", state_identity_trusted=False,
        )


def test_legacy_null_identity_conflict_detection_isolated(test_dsn, conn):
    """Acceptance #6: legacy state_identity IS NULL rows keep today's stricter
    (by_scope-only) conflict-detection semantics, isolated from the new identity path."""
    from memory_lab.conflicts.detector import ConflictSourceRow, detect_conflict_candidates

    ws_id = _insert_workspace(conn)
    legacy_rows = [
        ConflictSourceRow(
            content_id=str(uuid.uuid4()), workspace_id=ws_id, text="legacy anchor one, no identity",
            memory_type="anchor", classify_confidence=0.85, is_current=True,
            current_state_scope="legacy-broad-scope", state_identity=None,
        ),
        ConflictSourceRow(
            content_id=str(uuid.uuid4()), workspace_id=ws_id, text="legacy anchor two, no identity, same scope",
            memory_type="anchor", classify_confidence=0.85, is_current=True,
            current_state_scope="legacy-broad-scope", state_identity=None,
        ),
    ]
    candidates = detect_conflict_candidates(legacy_rows, workspace_id=ws_id)
    multi_anchor_hits = [c for c in candidates if c.detection_rule == "multiple_current_anchors_v1"]
    assert len(multi_anchor_hits) == 1, "two legacy no-identity rows sharing a scope must still be flagged"
    assert multi_anchor_hits[0].reason_codes[-1] == "legacy_no_state_identity"


def test_reingest_same_identity_is_idempotent(test_dsn, conn):
    """Acceptance #7: re-ingesting the same content_id with the same state_identity is
    idempotent -- no duplicate anchors."""
    from memory_lab.current_state.resolver import resolve_current_state_after_ingest

    ws_id = _insert_workspace(conn)
    content_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id, content_hash) VALUES (%s::uuid, %s::uuid, %s)",
            (content_id, ws_id, f"hash-{content_id}"),
        )
    conn.commit()

    kwargs = dict(
        workspace_id=ws_id, content_id=content_id, memory_type="decision",
        classify_confidence=0.85, content_text="idempotent re-ingest test",
        state_identity="idempotent-key",
    )
    first = resolve_current_state_after_ingest(conn, **kwargs)
    second = resolve_current_state_after_ingest(conn, **kwargs)

    assert first.idempotent is False
    assert second.idempotent is True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM cb_current_state_anchors WHERE workspace_id = %s::uuid AND content_id = %s::uuid",
            (ws_id, content_id),
        )
        assert cur.fetchone()[0] == 1


def test_no_automatic_backfill_from_scope(test_dsn, conn):
    """Acceptance #8: zero automatic backfill of state_identity from current_state_scope,
    anywhere in the write path -- group-only saves must never populate state_identity."""
    from memory_lab.api.services.api_adapter import ApiAdapter

    ws_id = _insert_workspace(conn)
    adapter = ApiAdapter(test_dsn)

    with patch("memory_lab.api.services.api_adapter._classify", return_value=_high_conf()):
        resp = adapter.create_content_minimal(
            content="decision: this has a clear scope but no explicit identity at all",
            workspace_id=ws_id, scope_hint="a-very-specific-narrow-scope-hint",
        )

    row = _content_row(conn, resp["content_id"])
    assert row["current_state_scope"] is not None
    assert row["state_identity"] is None, "scope must never be auto-promoted into state_identity"


def test_false_supersession_pattern_no_longer_reproducible(test_dsn, conn):
    """Acceptance #9 (coexistence half): the exact bug pattern from this investigation
    (two unrelated saves auto-classified into the same broad scope) no longer produces
    a false cs_supersedes_content_id link, because no state_identity means the write
    path never touches cb_current_state_anchors at all."""
    from memory_lab.api.services.api_adapter import ApiAdapter

    ws_id = _insert_workspace(conn)
    adapter = ApiAdapter(test_dsn)

    with patch("memory_lab.api.services.api_adapter._classify", return_value=_high_conf()):
        unrelated_a = adapter.create_content_minimal(
            content="RFC draft: search benchmark gold corpus methodology retrieval embeddings",
            workspace_id=ws_id, scope_hint="retrieval-embeddings",
        )
        unrelated_b = adapter.create_content_minimal(
            content="Curator and Orchestrator are distinct architectural layers in OpenCB",
            workspace_id=ws_id, scope_hint="retrieval-embeddings",
        )

    a_row = _content_row(conn, unrelated_a["content_id"])
    b_row = _content_row(conn, unrelated_b["content_id"])
    assert a_row["cs_supersedes_content_id"] is None
    assert b_row["cs_supersedes_content_id"] is None
    assert a_row["current_state_scope"] == b_row["current_state_scope"] == "retrieval-embeddings"
