from dataclasses import FrozenInstanceError

import pytest

from memory_lab.governance.state import (
    B25_LIMITATIONS,
    B25_NON_CLAIMS,
    GOVERNANCE_STATUSES,
    GovernanceProvenance,
    GovernanceRecordRef,
    GovernanceState,
    GovernanceValidationResult,
    validate_governance_state,
    validate_status,
    validate_status_transition,
    validate_tier,
)


def ref(workspace_id="workspace-a"):
    return GovernanceRecordRef(
        record_id="record-1",
        record_type="content_governance_state",
        workspace_id=workspace_id,
        content_id="content-1",
        source_ref="source-1",
    )


def provenance():
    return GovernanceProvenance(
        source_type="supplied_fixture",
        source_id="fixture-1",
        source_label="B25 public-safe fixture",
        created_by="unit-test",
        trace_id="trace-b25",
        created_at="2026-01-01T00:00:00Z",
        metadata={"scope": "data_only"},
    )


def state(**kwargs):
    values = dict(record_ref=ref(), status="active", tier="persistent", provenance=provenance(), state_reason="fixture")
    values.update(kwargs)
    return GovernanceState(**values)


def test_immutable_state_reference_and_provenance_structures():
    item = state()
    with pytest.raises(FrozenInstanceError):
        item.status = "archived"
    with pytest.raises(FrozenInstanceError):
        item.record_ref.workspace_id = "other"
    with pytest.raises(FrozenInstanceError):
        item.provenance.trace_id = "other"


def test_valid_state_creation_with_workspace_id():
    result = validate_governance_state(state())
    assert result.valid is True
    assert "B25-GOVERNANCE-STATE" in result.rule_ids
    assert "no_db_access" in result.limitations
    assert "not_db_backed_persistence" in result.non_claims


def test_missing_and_blank_workspace_are_rejected():
    missing = validate_governance_state(state(record_ref=ref(workspace_id="")))
    blank = validate_governance_state(state(record_ref=ref(workspace_id="   ")))
    assert missing.valid is False
    assert blank.valid is False
    assert any("workspace_id is required" in error for error in missing.errors)
    assert any("workspace_id is required" in error for error in blank.errors)


def test_invalid_status_and_invalid_tier_are_rejected():
    status_result = validate_status("production_ready")
    tier_result = validate_tier("runtime_only")
    assert status_result.valid is False
    assert tier_result.valid is False
    assert "B25-STATUS-ALLOWED" in status_result.rule_ids
    assert "B25-TIER-ALLOWED" in tier_result.rule_ids


def test_status_and_tier_remain_distinct_concepts():
    assert "active" in GOVERNANCE_STATUSES
    assert validate_tier("active").valid is False
    assert validate_status("persistent").valid is False
    item = state(status="active", tier="persistent")
    assert item.status != item.tier


def test_provenance_source_fields_are_data_only():
    item = state()
    assert item.provenance.source_type == "supplied_fixture"
    assert item.provenance.metadata == {"scope": "data_only"}
    assert "no_provider_call" in item.limitations
    assert "not_provider_backed_intelligence" in item.non_claims


def test_validation_result_shape_is_deterministic():
    result = validate_governance_state(state(status="not_allowed", tier="not_allowed"))
    assert isinstance(result, GovernanceValidationResult)
    assert result.valid is False
    assert isinstance(result.errors, tuple)
    assert isinstance(result.warnings, tuple)
    assert isinstance(result.rule_ids, tuple)
    assert result.limitations == B25_LIMITATIONS
    assert result.non_claims == B25_NON_CLAIMS


def test_status_transition_validation_is_pure_and_bounded():
    assert validate_status_transition("draft", "active").valid is True
    blocked = validate_status_transition("archived", "active")
    assert blocked.valid is False
    assert "B25-STATUS-TRANSITION" in blocked.rule_ids


def test_no_persistence_or_mutation_claim():
    item = state()
    assert "no_storage_mutation" in item.limitations
    assert "no_db_access" in item.limitations
    assert "not_production_governance_runtime" in item.limitations
    assert "not_live_governance_lifecycle" in item.non_claims
