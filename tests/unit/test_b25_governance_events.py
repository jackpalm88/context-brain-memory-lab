from memory_lab.governance.state import GovernanceProvenance, GovernanceRecordRef
from memory_lab.governance.state_events import (
    B25_STATE_EVENT_TYPE,
    build_governance_state_event_contract,
    data_only_event_capability,
    governance_state_event_to_dict,
    validate_governance_state_event_contract,
)


def ref(workspace_id="workspace-a"):
    return GovernanceRecordRef(
        record_id="record-1",
        record_type="content_governance_state",
        workspace_id=workspace_id,
        content_id="content-1",
    )


def provenance():
    return GovernanceProvenance(
        source_type="supplied_fixture",
        source_id="fixture-1",
        source_label="B25 fixture",
        created_by="unit-test",
        trace_id="trace-b25",
        created_at="2026-01-01T00:00:00Z",
    )


def test_event_contract_is_data_only_and_validates():
    event = build_governance_state_event_contract(ref(), provenance(), previous_status="draft", next_status="active")
    result = validate_governance_state_event_contract(event)
    assert event.event_type == B25_STATE_EVENT_TYPE
    assert result.valid is True
    assert "B25-STATE-EVENT-DATA-ONLY" in result.rule_ids


def test_event_includes_workspace_record_ref_and_provenance():
    event = build_governance_state_event_contract(ref("workspace-a"), provenance())
    as_dict = governance_state_event_to_dict(event)
    assert as_dict["workspace_id"] == "workspace-a"
    assert as_dict["record_ref"]["record_id"] == "record-1"
    assert as_dict["provenance"]["source_id"] == "fixture-1"


def test_event_includes_previous_next_status_and_tier_when_supplied():
    event = build_governance_state_event_contract(
        ref(),
        provenance(),
        previous_status="draft",
        next_status="active",
        previous_tier="probationary",
        next_tier="persistent",
    )
    as_dict = governance_state_event_to_dict(event)
    assert as_dict["previous_status"] == "draft"
    assert as_dict["next_status"] == "active"
    assert as_dict["previous_tier"] == "probationary"
    assert as_dict["next_tier"] == "persistent"


def test_event_includes_limitations_non_claims_and_no_durable_claim():
    event = build_governance_state_event_contract(ref(), provenance())
    as_dict = governance_state_event_to_dict(event)
    assert "no_db_access" in as_dict["limitations"]
    assert "no_storage_mutation" in as_dict["limitations"]
    assert "not_db_backed_persistence" in as_dict["non_claims"]
    assert "durable_governance_emission" not in as_dict["non_claims"]


def test_event_capability_does_not_call_db_network_provider_or_mutate():
    capability = data_only_event_capability()
    assert capability["requires_db"] is False
    assert capability["requires_provider"] is False
    assert capability["requires_private_context_brain"] is False
    assert capability["mutates_state"] is False
    assert "caller_supplied_input_only" in capability["limitations"]
