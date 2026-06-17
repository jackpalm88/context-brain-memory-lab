from dataclasses import replace

from memory_lab.governance.state import GovernanceProvenance, GovernanceRecordRef, GovernanceState
from memory_lab.governance.state_events import GovernanceStateEventContract, build_governance_state_event_contract
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


def _state(workspace_id="ws-a", record_id="rec-1"):
    return GovernanceState(
        record_ref=GovernanceRecordRef(record_id=record_id, record_type="content", workspace_id=workspace_id, content_id="content-1"),
        status="active",
        tier="persistent",
        provenance=_provenance(),
    )


def test_same_content_id_in_different_workspaces_does_not_collide():
    backend = InMemoryPersistenceBackend()
    a = ContentPersistenceRecord(content_id="same", workspace_id="ws-a", text="A")
    b = ContentPersistenceRecord(content_id="same", workspace_id="ws-b", text="B")
    backend.put_content_record(a)
    backend.put_content_record(b)
    assert backend.get_content_record("ws-a", "same").value == a
    assert backend.get_content_record("ws-b", "same").value == b


def test_cross_workspace_read_is_isolated_as_not_found():
    backend = InMemoryPersistenceBackend()
    backend.put_content_record(ContentPersistenceRecord(content_id="c1", workspace_id="ws-a", text="A"))
    result = backend.get_content_record("ws-b", "c1")
    assert result.ok is False
    assert result.error.code == "not_found"


def test_governance_state_same_record_id_is_workspace_scoped():
    backend = InMemoryPersistenceBackend()
    state_a = _state("ws-a", "same")
    state_b = _state("ws-b", "same")
    backend.put_governance_state(state_a)
    backend.put_governance_state(state_b)
    assert backend.get_governance_state("ws-a", "same").value == state_a
    assert backend.get_governance_state("ws-b", "same").value == state_b


def test_governance_event_workspace_must_match_record_ref():
    backend = InMemoryPersistenceBackend()
    state = _state("ws-a", "rec-1")
    event = build_governance_state_event_contract(state.record_ref, state.provenance, next_status="active", next_tier="persistent")
    mismatched = replace(event, workspace_id="ws-b")
    result = backend.append_governance_event(mismatched)
    assert result.ok is False
    assert result.error.code in {"invalid_governance_event", "workspace_boundary_violation"}


def test_list_operations_are_workspace_isolated():
    backend = InMemoryPersistenceBackend()
    backend.put_content_record(ContentPersistenceRecord(content_id="a", workspace_id="ws-a"))
    backend.put_content_record(ContentPersistenceRecord(content_id="b", workspace_id="ws-b"))
    assert [record.content_id for record in backend.list_content_records("ws-a").value] == ["a"]
    assert [record.content_id for record in backend.list_content_records("ws-b").value] == ["b"]


def test_event_listing_without_record_id_stays_in_workspace():
    backend = InMemoryPersistenceBackend()
    state_a = _state("ws-a", "a")
    state_b = _state("ws-b", "b")
    event_a = build_governance_state_event_contract(state_a.record_ref, state_a.provenance, next_status="active", next_tier="persistent")
    event_b = build_governance_state_event_contract(state_b.record_ref, state_b.provenance, next_status="active", next_tier="persistent")
    backend.append_governance_event(event_a)
    backend.append_governance_event(event_b)
    assert backend.list_governance_events("ws-a").value == (event_a,)
    assert backend.list_governance_events("ws-b").value == (event_b,)
