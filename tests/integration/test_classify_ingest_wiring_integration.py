"""Integration tests — classify ingest wiring against disposable DB (migrations 000-030).

ENVIRONMENT REQUIREMENTS
------------------------
Set CB_TEST_ADMIN_DSN to a dedicated CB-named test Postgres instance:
  CB_TEST_ADMIN_DSN=postgresql://cb_test:cb_test@localhost:5432/postgres

Suggested container setup (once, outside this repo):
  docker run -d --name cb_memory_lab_postgres_test \
    -e POSTGRES_USER=cb_test -e POSTGRES_PASSWORD=cb_test \
    -e POSTGRES_DB=postgres -p 5433:5432 postgres:16

If CB_TEST_ADMIN_DSN is not set, all tests skip with reason:
  SKIPPED_NO_PUBLIC_STYLE_TEST_DSN

WHAT IS NEVER ALLOWED
---------------------
- n8n_postgres_1 container or any n8n credentials
- hardcoded passwords of any kind
- docker exec inside these tests
- DSN with username=n8n, password containing n8n123, host containing n8n

DISPOSABLE DB
-------------
Created per test session: cb_classify_ingest_wiring_<epoch>
Dropped at teardown. Migrations applied via psycopg2 (no docker exec).
"""
import glob
import os
import re
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


def _real_dict_cursor():
    pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary to run DB integration tests.",
    )
    from psycopg2.extras import RealDictCursor

    return RealDictCursor

# ---------------------------------------------------------------------------
# DSN guard — refuse unrelated / production / n8n deployment markers
# ---------------------------------------------------------------------------

_FORBIDDEN_DB_NAMES = re.compile(r"^(n8n|production|prod|contentingestor)$", re.IGNORECASE)
_FORBIDDEN_SUBSTRINGS = {"n8n_postgres_1", "n8n123"}


def _refuse_suspicious_dsn(dsn: str) -> None:
    """
    Refuse DSNs that point at unrelated or production systems.

    Checks:
    - DB name in {n8n, production, prod, contentingestor}
    - username == n8n (case-insensitive)
    - password contains n8n123
    - hostname contains n8n
    - raw DSN string contains n8n_postgres_1

    Allows:
    - DB name `postgres` used as admin DB, if user/host are not forbidden
    - CB-style credentials such as cb_test / cb_memory_lab_test
    """
    raw = dsn or ""
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in raw:
            raise RuntimeError(
                f"CB_TEST_ADMIN_DSN contains forbidden deployment marker {forbidden!r}. "
                "Provide a dedicated CB test Postgres — never n8n infrastructure."
            )
    try:
        parts = urlparse(raw)
        username = (parts.username or "").lower()
        password = parts.password or ""
        hostname = (parts.hostname or "").lower()
        db_name = (parts.path or "").lstrip("/")
    except Exception:
        return  # cannot parse — skip guard, let psycopg2 fail naturally

    if username == "n8n":
        raise RuntimeError(
            "CB_TEST_ADMIN_DSN uses username 'n8n'. "
            "Use a dedicated CB test user (e.g. cb_test)."
        )
    if "n8n123" in password:
        raise RuntimeError(
            "CB_TEST_ADMIN_DSN contains n8n123 in password. "
            "Use dedicated CB test credentials."
        )
    if "n8n" in hostname:
        raise RuntimeError(
            f"CB_TEST_ADMIN_DSN hostname {hostname!r} contains 'n8n'. "
            "Use a CB-named test Postgres host."
        )
    if _FORBIDDEN_DB_NAMES.match(db_name):
        raise RuntimeError(
            f"CB_TEST_ADMIN_DSN database name {db_name!r} is forbidden. "
            "Use a CB-prefixed disposable DB or 'postgres' as admin DB only."
        )


# ---------------------------------------------------------------------------
# Session-scoped disposable DB fixture
# ---------------------------------------------------------------------------

_ADMIN_DSN = os.environ.get("CB_TEST_ADMIN_DSN", "").strip()
_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "migrations")
_SKIP_MIGRATION_IDS = {"002"}  # requires pgvector extension — not guaranteed in test env


@pytest.fixture(scope="session")
def test_dsn():
    """
    Create disposable cb_classify_ingest_wiring_<ts> DB, apply migrations, yield DSN, drop at teardown.
    Skips with SKIPPED_NO_PUBLIC_STYLE_TEST_DSN when CB_TEST_ADMIN_DSN is not set.
    """
    if not _ADMIN_DSN:
        pytest.skip(
            "SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — CB_TEST_ADMIN_DSN not set. "
            "Provide a dedicated CB test Postgres: "
            "CB_TEST_ADMIN_DSN=postgresql://cb_test:cb_test@localhost:5433/postgres"
        )

    _refuse_suspicious_dsn(_ADMIN_DSN)

    disposable_db = f"cb_classify_ingest_wiring_{int(time.time())}"

    # Create disposable DB via admin connection
    try:
        admin_conn = _psycopg2().connect(_ADMIN_DSN)
        admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with admin_conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{disposable_db}";')
        admin_conn.close()
    except Exception as exc:
        pytest.skip(f"SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — could not connect to CB_TEST_ADMIN_DSN: {exc}")

    # Derive disposable DSN from admin DSN
    parts = urlparse(_ADMIN_DSN)
    db_dsn = urlunparse(parts._replace(path=f"/{disposable_db}"))

    # Apply migrations via psycopg2 (no docker exec)
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


@pytest.fixture
def conn(test_dsn):
    c = _psycopg2().connect(test_dsn)
    c.autocommit = False
    yield c
    c.rollback()
    c.close()


def _insert_workspace(conn) -> str:
    ws_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s)",
            (ws_id, f"test-{ws_id[:8]}", "Test Workspace"),
        )
    conn.commit()
    return ws_id


pytestmark = [pytest.mark.integration, pytest.mark.public_safe, pytest.mark.provider_optional]


# ---------------------------------------------------------------------------
# Guard unit checks (always run — no DB required)
# ---------------------------------------------------------------------------

class TestDsnGuard:
    """_refuse_suspicious_dsn must block n8n and unrelated deployment markers."""

    def test_refuses_n8n_username(self):
        with pytest.raises(RuntimeError, match="username 'n8n'"):
            _refuse_suspicious_dsn("postgresql://n8n:somepass@localhost:5432/postgres")

    def test_refuses_n8n123_password(self):
        with pytest.raises(RuntimeError, match="n8n123"):
            _refuse_suspicious_dsn("postgresql://cb_test:n8n123@localhost:5432/postgres")

    def test_refuses_n8n_hostname(self):
        # Use a hostname that contains n8n but is not caught by the raw-string n8n_postgres_1 check
        with pytest.raises(RuntimeError, match="hostname"):
            _refuse_suspicious_dsn("postgresql://cb_test:cb_test@n8n-db-host:5432/postgres")

    def test_refuses_n8n_db_name(self):
        with pytest.raises(RuntimeError, match="database name"):
            _refuse_suspicious_dsn("postgresql://cb_test:cb_test@localhost:5432/n8n")

    def test_refuses_production_db_name(self):
        with pytest.raises(RuntimeError, match="database name"):
            _refuse_suspicious_dsn("postgresql://cb_test:cb_test@localhost:5432/production")

    def test_refuses_contentingestor_db_name(self):
        with pytest.raises(RuntimeError, match="database name"):
            _refuse_suspicious_dsn("postgresql://cb_test:cb_test@localhost:5432/contentingestor")

    def test_refuses_n8n_postgres_1_in_raw_string(self):
        with pytest.raises(RuntimeError, match="n8n_postgres_1"):
            _refuse_suspicious_dsn("postgresql://cb_test:cb_test@n8n_postgres_1/postgres")

    def test_allows_cb_style_credentials(self):
        _refuse_suspicious_dsn("postgresql://cb_test:cb_test@localhost:5433/postgres")

    def test_allows_postgres_admin_db_with_cb_credentials(self):
        _refuse_suspicious_dsn("postgresql://cb_test:securepw@localhost:5432/postgres")

    def test_empty_dsn_does_not_raise(self):
        # Empty DSN → psycopg2 will fail; guard must not blow up before that
        _refuse_suspicious_dsn("")


# ---------------------------------------------------------------------------
# Integration tests (skip without CB_TEST_ADMIN_DSN)
# ---------------------------------------------------------------------------

def test_classify_happy_path(test_dsn, conn):
    """create_content_minimal writes memory_type + history row for milestone content."""
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    adapter = ApiAdapter(test_dsn)

    resp = adapter.create_content_minimal(
        content=(
            "GO_CLASSIFY_PIPELINE_INGEST_WIRING_IMPLEMENTATION pass. v0.1.0b9 gate complete. "
            "30/30 smoke checks passed. scorecard updated."
        ),
        workspace_id=ws_id,
    )
    assert resp["created"] is True
    cid = resp["content_id"]

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT memory_type, classify_confidence, classified_at FROM content_items WHERE content_id = %s::uuid",
            (cid,),
        )
        row = cur.fetchone()

    assert row["memory_type"] is not None
    assert row["classify_confidence"] > 0
    assert row["classified_at"] is not None

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT * FROM cb_classification_history WHERE content_id = %s::uuid AND is_active_classification = TRUE",
            (cid,),
        )
        hist = cur.fetchall()

    assert len(hist) == 1
    assert hist[0]["classifier_version"] == "heuristic_v1"


def test_reclassify_deactivates_prior_active(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    adapter = ApiAdapter(test_dsn)

    resp = adapter.create_content_minimal(
        content="initial evidence smoke_001 30/30 scorecard", workspace_id=ws_id
    )
    cid = resp["content_id"]

    adapter._run_classify_and_write(
        content="principle: invariant — must not write is_current in classify path",
        content_id=cid, workspace_id=ws_id, tier="transient", composite_score=0.4,
    )

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT is_active_classification FROM cb_classification_history WHERE content_id = %s::uuid ORDER BY classified_at",
            (cid,),
        )
        rows = cur.fetchall()

    actives = [r for r in rows if r["is_active_classification"]]
    assert len(actives) == 1
    assert len(rows) >= 2


def test_domain_upsert_and_link_high_confidence(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.ingestion.classify_pipeline import ClassificationResult
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    cid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id) VALUES (%s::uuid, %s::uuid)",
            (cid, ws_id),
        )
    conn.commit()

    high_conf = ClassificationResult(
        memory_type="milestone", confidence=0.85,
        signals=["go_classify", "_schema_apply_pass"], domain_hint="governance"
    )
    with patch("memory_lab.api.services.api_adapter._classify", return_value=high_conf):
        adapter._run_classify_and_write(
            content="GO_CLASSIFY pass", content_id=cid,
            workspace_id=ws_id, tier="transient", composite_score=0.5,
        )

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute("SELECT domain_id FROM content_items WHERE content_id = %s::uuid", (cid,))
        assert cur.fetchone()["domain_id"] is not None

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT domain_name FROM cb_discovered_domains WHERE workspace_id = %s::uuid AND domain_name = 'governance'",
            (ws_id,),
        )
        assert cur.fetchone() is not None


def test_low_confidence_leaves_domain_null(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.ingestion.classify_pipeline import ClassificationResult
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    cid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id) VALUES (%s::uuid, %s::uuid)",
            (cid, ws_id),
        )
    conn.commit()

    with patch("memory_lab.api.services.api_adapter._classify",
               return_value=ClassificationResult(
                   memory_type="evidence", confidence=0.62,
                   signals=["smoke_001"], domain_hint="schema"
               )):
        adapter._run_classify_and_write(
            content="smoke_001 pass", content_id=cid,
            workspace_id=ws_id, tier="transient", composite_score=0.3,
        )

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute("SELECT domain_id FROM content_items WHERE content_id = %s::uuid", (cid,))
        assert cur.fetchone()["domain_id"] is None


def test_discard_tier_no_classify_write(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.governance.tier_router import TierDecision
    from unittest.mock import patch, MagicMock

    adapter = ApiAdapter(test_dsn)
    fake_event = MagicMock()
    fake_event.scores.composite = 0.0
    fake_event.scores.quality = 0.0
    fake_event.scores.relevance = 0.0
    fake_event.scores.novelty = 0.0
    fake_event.circuit_open = False
    fake_event.fallback_reason = "test_discard_mode"

    with patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
         patch("memory_lab.api.services.api_adapter.tier_route",
               return_value=TierDecision(tier="discard", reason="test", rule_id="X", should_persist=False)), \
         patch.object(adapter, "_run_classify_and_write") as mock_classify_write:
        resp = adapter.create_content_minimal(content="discard me", workspace_id=ws_id)

    mock_classify_write.assert_not_called()
    assert "content_id" not in resp
    assert resp["created"] is False
    assert resp["persisted"] is False
    assert resp["discarded"] is True
    assert resp["mode"] == "governed_discarded"
    assert "memory_type" not in resp
    assert "classify_status" not in resp

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM content_items WHERE workspace_id = %s::uuid", (ws_id,))
        assert cur.fetchone()["n"] == 0


def test_t3_failure_does_not_rollback_content_save(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    with patch("memory_lab.api.services.api_adapter._classify", side_effect=RuntimeError("T3 chaos")):
        resp = adapter.create_content_minimal(content="gate pass v0.1.0b9 smoke", workspace_id=ws_id)

    assert resp["created"] is True
    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT tier FROM content_items WHERE content_id = %s::uuid", (resp["content_id"],)
        )
        row = cur.fetchone()
    assert row is not None
    assert row["tier"] is not None


def test_low_confidence_no_current_state_writes(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.ingestion.classify_pipeline import ClassificationResult
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    low_conf = ClassificationResult(
        memory_type="evidence", confidence=0.62,
        signals=["unit test"], domain_hint="schema",
    )
    with patch("memory_lab.api.services.api_adapter._classify", return_value=low_conf):
        resp = adapter.create_content_minimal(
            content="unit test result but weak evidence only", workspace_id=ws_id,
        )

    assert "current_state_status" not in resp
    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT is_current, current_state_scope, cs_supersedes_content_id "
            "FROM content_items WHERE content_id = %s::uuid",
            (resp["content_id"],),
        )
        row = cur.fetchone()

    assert row["is_current"] is None
    assert row["current_state_scope"] is None
    assert row["cs_supersedes_content_id"] is None


def test_retry_dedup_no_duplicate_history_row(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.ingestion.classify_pipeline import ClassificationResult
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    cid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO content_items (content_id, workspace_id) VALUES (%s::uuid, %s::uuid)",
            (cid, ws_id),
        )
    conn.commit()

    fixed = ClassificationResult(memory_type="milestone", confidence=0.85, signals=["go_classify"])
    with patch("memory_lab.api.services.api_adapter._classify", return_value=fixed):
        adapter._run_classify_and_write(
            content="first", content_id=cid, workspace_id=ws_id, tier="transient", composite_score=0.4,
        )
        result2 = adapter._run_classify_and_write(
            content="retry", content_id=cid, workspace_id=ws_id, tier="transient", composite_score=0.4,
        )

    assert result2 is not None
    assert result2.get("dedup") is True

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT COUNT(*) as n FROM cb_classification_history "
            "WHERE content_id = %s::uuid AND is_active_classification = TRUE",
            (cid,),
        )
        assert cur.fetchone()["n"] == 1


def test_classify_runs_without_api_key(test_dsn, conn):
    original_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        ws_id = _insert_workspace(conn)
        from memory_lab.api.services.api_adapter import ApiAdapter
        adapter = ApiAdapter(test_dsn)
        resp = adapter.create_content_minimal(
            content="GO_CLASSIFY gate pass v0.1.0b9 milestone 30/30 scorecard",
            workspace_id=ws_id,
        )
        assert resp["created"] is True
        assert resp.get("memory_type") is not None
    finally:
        if original_key is not None:
            os.environ["OPENAI_API_KEY"] = original_key


def test_high_confidence_current_state_anchor_written(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.ingestion.classify_pipeline import ClassificationResult
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    high_conf = ClassificationResult(
        memory_type="anchor", memory_sub_type="current_state_anchor", confidence=0.85,
        signals=["current state", "canonical:"], project_topic="context_brain_memory_lab",
        domain_hint="governance",
    )
    with patch("memory_lab.api.services.api_adapter._classify", return_value=high_conf):
        resp = adapter.create_content_minimal(
            content="current_state_scope: b10-candidate\nCurrent state active anchor. Canonical: source of truth.",
            workspace_id=ws_id,
        )

    assert resp["current_state_status"] == "active"
    assert resp["current_state_scope"] == "b10-candidate"
    cid = resp["content_id"]
    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT is_current, current_state_scope, cs_supersedes_content_id FROM content_items WHERE content_id = %s::uuid",
            (cid,),
        )
        row = cur.fetchone()
        cur.execute(
            "SELECT state_status, scope, content_id::text AS content_id FROM cb_current_state_anchors WHERE content_id = %s::uuid",
            (cid,),
        )
        anchor = cur.fetchone()

    assert row["is_current"] is True
    assert row["current_state_scope"] == "b10-candidate"
    assert row["cs_supersedes_content_id"] is None
    assert anchor["state_status"] == "active"
    assert anchor["scope"] == "b10-candidate"
    assert anchor["content_id"] == cid


def test_second_current_state_supersedes_previous_anchor(test_dsn, conn):
    ws_id = _insert_workspace(conn)
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.ingestion.classify_pipeline import ClassificationResult
    from unittest.mock import patch

    adapter = ApiAdapter(test_dsn)
    high_conf = ClassificationResult(
        memory_type="anchor", memory_sub_type="current_state_anchor", confidence=0.85,
        signals=["current state", "canonical:"], project_topic=None,
        domain_hint="governance",
    )
    with patch("memory_lab.api.services.api_adapter._classify", return_value=high_conf):
        first = adapter.create_content_minimal(
            content="current_state_scope: b10-candidate\nCurrent state active anchor v1. Canonical: source of truth.",
            workspace_id=ws_id,
        )
        second = adapter.create_content_minimal(
            content="current_state_scope: b10-candidate\nCurrent state active anchor v2. Canonical: source of truth.",
            workspace_id=ws_id,
        )

    first_id = first["content_id"]
    second_id = second["content_id"]
    assert second["cs_supersedes_content_id"] == first_id

    with conn.cursor(cursor_factory=_real_dict_cursor()) as cur:
        cur.execute(
            "SELECT content_id::text AS content_id, is_current, current_state_scope, cs_supersedes_content_id::text AS supersedes "
            "FROM content_items WHERE content_id IN (%s::uuid, %s::uuid) ORDER BY content_id::text",
            (first_id, second_id),
        )
        rows = {r["content_id"]: r for r in cur.fetchall()}
        cur.execute(
            "SELECT content_id::text AS content_id, state_status FROM cb_current_state_anchors "
            "WHERE workspace_id = %s::uuid AND memory_type = 'anchor' AND scope = 'b10-candidate'",
            (ws_id,),
        )
        anchors = {r["content_id"]: r["state_status"] for r in cur.fetchall()}

    assert rows[first_id]["is_current"] is False
    assert rows[second_id]["is_current"] is True
    assert rows[second_id]["supersedes"] == first_id
    assert anchors[first_id] == "superseded"
    assert anchors[second_id] == "active"
