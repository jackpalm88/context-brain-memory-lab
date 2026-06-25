import glob
import os
import uuid
from pathlib import Path

import pytest

from memory_lab.governance.state import GovernanceProvenance, GovernanceRecordRef, GovernanceState
from memory_lab.governance.state_events import build_governance_state_event_contract
from memory_lab.persistence.factory import build_persistence_backend
from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend
from memory_lab.persistence.results import ContentPersistenceRecord


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_db,
    pytest.mark.skipped_without_env,
]

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_SKIP_MIGRATION_IDS = {"002"}  # pgvector is M3/out of M2 round-trip scope.
_DSN = (os.environ.get("CB_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
_SKIP_REASON = (
    "CB_TEST_DATABASE_URL/DATABASE_URL not set; real Postgres persistence round-trip is opt-in "
    "and skipped in empty-env deterministic gates"
)


def _psycopg2():
    return pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary to run DB integration tests.",
    )


def _apply_migrations(dsn: str) -> None:
    psycopg2 = _psycopg2()
    conn = psycopg2.connect(dsn)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        for mig_path in sorted(glob.glob(str(_MIGRATIONS_DIR / "*.sql"))):
            migration_id = os.path.basename(mig_path).split("_")[0]
            if migration_id in _SKIP_MIGRATION_IDS:
                continue
            sql = Path(mig_path).read_text(encoding="utf-8")
            if migration_id == "000":
                sql = sql.replace("CREATE EXTENSION IF NOT EXISTS vector;", "-- pgvector stripped for M2 test env")
            with conn.cursor() as cur:
                cur.execute(sql)
    finally:
        conn.close()


@pytest.fixture(scope="session")
def postgres_dsn():
    if not _DSN:
        pytest.skip(_SKIP_REASON)
    try:
        _apply_migrations(_DSN)
    except Exception as exc:
        pytest.skip(f"SKIPPED_POSTGRES_M2_ROUNDTRIP_DSN_UNUSABLE — could not apply migrations/connect: {exc}")
    return _DSN


def _provenance():
    return GovernanceProvenance(
        source_type="test",
        source_id="m2-task3",
        source_label="M2 Task 3 integration test",
        created_by="pytest",
        trace_id="trace-m2-task3",
        created_at="2026-06-25T00:00:00Z",
        metadata={"scope": "real-postgres-roundtrip"},
    )


def test_m2_postgres_persistence_integration_is_opt_in(monkeypatch, postgres_dsn):
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    backend = build_persistence_backend()
    assert isinstance(backend, PostgresPersistenceBackend)
    assert backend.database_url == postgres_dsn


def test_m2_real_postgres_content_and_governance_round_trip(postgres_dsn):
    backend = PostgresPersistenceBackend(postgres_dsn)
    workspace_id = str(uuid.uuid4())
    content_id = str(uuid.uuid4())
    record_id = f"m2-task3-{content_id}"

    record = ContentPersistenceRecord(
        content_id=content_id,
        workspace_id=workspace_id,
        text="M2 Task 3 real Postgres save load round trip text.",
        title="M2 Task 3 round trip",
        metadata={"milestone": "M2", "task": "3"},
        governance_state_id=record_id,
    )
    saved_content = backend.put_content_record(record)
    assert saved_content.ok is True
    assert saved_content.metadata.live_backend_used is True
    assert saved_content.metadata.requires_db is True
    assert saved_content.metadata.uses_vector_db is False

    loaded_content = backend.get_content_record(workspace_id, content_id)
    assert loaded_content.ok is True
    assert loaded_content.value == record

    state = GovernanceState(
        record_ref=GovernanceRecordRef(
            record_id=record_id,
            record_type="content",
            workspace_id=workspace_id,
            content_id=content_id,
        ),
        status="active",
        tier="persistent",
        provenance=_provenance(),
        state_reason="M2 Task 3 integration round-trip",
    )
    saved_state = backend.put_governance_state(state)
    assert saved_state.ok is True

    loaded_state = backend.get_governance_state(workspace_id, record_id)
    assert loaded_state.ok is True
    assert loaded_state.value == state

    event = build_governance_state_event_contract(
        record_ref=state.record_ref,
        provenance=state.provenance,
        previous_status="draft",
        next_status="active",
        previous_tier="probationary",
        next_tier="persistent",
        event_reason="M2 Task 3 round-trip event",
    )
    appended = backend.append_governance_event(event)
    assert appended.ok is True

    listed = backend.list_governance_events(workspace_id, record_id)
    assert listed.ok is True
    assert listed.value[-1] == event

    listed_content = backend.list_content_records(workspace_id)
    assert listed_content.ok is True
    assert record in listed_content.value
