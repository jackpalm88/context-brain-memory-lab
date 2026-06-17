from memory_lab.governance.state import GovernanceProvenance, GovernanceRecordRef, GovernanceState
from memory_lab.governance.state_events import build_governance_state_event_contract
from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend
from memory_lab.persistence.results import ContentPersistenceRecord


def _provenance():
    return GovernanceProvenance(
        source_type="test",
        source_id="src-1",
        source_label="unit test",
        created_by="tester",
        trace_id="trace-1",
        created_at="2026-06-17T00:00:00Z",
    )


def _state(workspace_id="ws-a", record_id="rec-1", content_id="content-1"):
    return GovernanceState(
        record_ref=GovernanceRecordRef(record_id=record_id, record_type="content", workspace_id=workspace_id, content_id=content_id),
        status="active",
        tier="persistent",
        provenance=_provenance(),
    )


def test_in_memory_backend_put_get_content_record():
    backend = InMemoryPersistenceBackend()
    record = ContentPersistenceRecord(content_id="c1", workspace_id="ws1", text="hello", title="Hello")
    put = backend.put_content_record(record)
    got = backend.get_content_record("ws1", "c1")
    assert put.ok is True
    assert got.ok is True
    assert got.value == record
    assert got.metadata.live_backend_used is False


def test_repeated_content_writes_are_idempotent_and_deterministic():
    backend = InMemoryPersistenceBackend()
    first = ContentPersistenceRecord(content_id="c1", workspace_id="ws1", text="first")
    second = ContentPersistenceRecord(content_id="c1", workspace_id="ws1", text="second")
    assert backend.put_content_record(first).ok is True
    assert backend.put_content_record(second).ok is True
    records = backend.list_content_records("ws1")
    assert records.ok is True
    assert records.value == (second,)


def test_in_memory_backend_put_get_governance_state():
    backend = InMemoryPersistenceBackend()
    state = _state()
    assert backend.put_governance_state(state).ok is True
    got = backend.get_governance_state("ws-a", "rec-1")
    assert got.ok is True
    assert got.value == state


def test_in_memory_backend_append_and_list_governance_events():
    backend = InMemoryPersistenceBackend()
    state = _state()
    event = build_governance_state_event_contract(
        record_ref=state.record_ref,
        provenance=state.provenance,
        previous_status="draft",
        next_status="active",
        previous_tier="probationary",
        next_tier="persistent",
    )
    appended = backend.append_governance_event(event)
    listed = backend.list_governance_events("ws-a", "rec-1")
    assert appended.ok is True
    assert listed.ok is True
    assert listed.value == (event,)


def test_missing_record_returns_structured_not_found_error():
    backend = InMemoryPersistenceBackend()
    result = backend.get_content_record("ws1", "missing")
    assert result.ok is False
    assert result.error.code == "not_found"
    assert result.error.field == "content_id"


def test_invalid_input_returns_result_not_live_exception():
    backend = InMemoryPersistenceBackend()
    result = backend.put_content_record({"content_id": "c1"})
    assert result.ok is False
    assert result.error.code == "invalid_workspace_id"
