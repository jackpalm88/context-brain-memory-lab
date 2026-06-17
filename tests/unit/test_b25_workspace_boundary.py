from memory_lab.governance.state import GovernanceRecordRef, GovernanceState, GovernanceProvenance
from memory_lab.governance.workspace import assert_same_workspace, validate_workspace_boundary, validate_workspace_id


def ref(record_id="record-1", workspace_id="workspace-a"):
    return GovernanceRecordRef(record_id=record_id, record_type="content_governance_state", workspace_id=workspace_id)


def provenance():
    return GovernanceProvenance(
        source_type="supplied_fixture",
        source_id="fixture-1",
        source_label="B25 fixture",
        created_by="unit-test",
        trace_id="trace-b25",
        created_at="2026-01-01T00:00:00Z",
    )


def test_valid_single_workspace_passes():
    result = validate_workspace_boundary([ref("record-1", "workspace-a"), ref("record-2", "workspace-a")])
    assert result.valid is True
    assert "B25-WORKSPACE-BOUNDARY" in result.rule_ids


def test_blank_workspace_rejected():
    result = validate_workspace_id("   ")
    assert result.valid is False
    assert result.errors == ("workspace_id is required",)


def test_missing_workspace_rejected():
    result = validate_workspace_id(None)
    assert result.valid is False
    assert result.errors == ("workspace_id is required",)


def test_mixed_workspace_ids_rejected():
    result = assert_same_workspace([ref("record-1", "workspace-a"), ref("record-2", "workspace-b")])
    assert result.valid is False
    assert any("mixed workspace_ids" in error for error in result.errors)


def test_explicit_workspace_context_must_match_record_workspace():
    result = validate_workspace_boundary([ref("record-1", "workspace-a")], workspace_id="workspace-b")
    assert result.valid is False
    assert any("does not match explicit workspace context" in error for error in result.errors)


def test_supports_state_objects_and_mapping_refs():
    item = GovernanceState(record_ref=ref("record-1", "workspace-a"), status="active", tier="persistent", provenance=provenance())
    mapping = {"record_ref": {"workspace_id": "workspace-a"}}
    result = validate_workspace_boundary([item, mapping], workspace_id="workspace-a")
    assert result.valid is True


def test_deterministic_error_object_shape_and_non_claims():
    result = validate_workspace_boundary([{"record_ref": {"workspace_id": ""}}])
    assert result.valid is False
    assert isinstance(result.errors, tuple)
    assert isinstance(result.warnings, tuple)
    assert isinstance(result.rule_ids, tuple)
    assert "no_live_tenant_lookup" in result.limitations
    assert "no_auth_or_rbac_enforcement" in result.limitations
    assert "not_api_runtime" in result.limitations
