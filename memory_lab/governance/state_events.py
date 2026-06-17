"""B25 data-only governance state event contracts.

Events built here are plain deterministic contract objects over supplied data. They are not durable event emission, storage writers, runtime hooks, or API integrations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from memory_lab.governance.state import (
    B25_GOVERNANCE_STATE_MODE,
    B25_LIMITATIONS,
    B25_NON_CLAIMS,
    GovernanceProvenance,
    GovernanceRecordRef,
    GovernanceValidationResult,
    validate_provenance,
    validate_record_ref,
    validate_status,
    validate_tier,
    validation_fail,
    validation_pass,
)
from memory_lab.governance.workspace import validate_workspace_boundary

B25_STATE_EVENT_TYPE = "b25_data_only_governance_state_event_v1"

@dataclass(frozen=True)
class GovernanceStateEventContract:
    event_type: str
    workspace_id: str
    record_ref: GovernanceRecordRef
    provenance: GovernanceProvenance
    previous_status: str | None = None
    next_status: str | None = None
    previous_tier: str | None = None
    next_tier: str | None = None
    event_reason: str | None = None
    limitations: tuple[str, ...] = B25_LIMITATIONS
    non_claims: tuple[str, ...] = B25_NON_CLAIMS
    mode: str = B25_GOVERNANCE_STATE_MODE

def build_governance_state_event_contract(
    record_ref: GovernanceRecordRef,
    provenance: GovernanceProvenance,
    previous_status: str | None = None,
    next_status: str | None = None,
    previous_tier: str | None = None,
    next_tier: str | None = None,
    event_reason: str | None = None,
) -> GovernanceStateEventContract:
    return GovernanceStateEventContract(
        event_type=B25_STATE_EVENT_TYPE,
        workspace_id=record_ref.workspace_id,
        record_ref=record_ref,
        provenance=provenance,
        previous_status=previous_status,
        next_status=next_status,
        previous_tier=previous_tier,
        next_tier=next_tier,
        event_reason=event_reason,
    )

def validate_governance_state_event_contract(event: GovernanceStateEventContract) -> GovernanceValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    rule_ids: list[str] = ["B25-STATE-EVENT-DATA-ONLY"]
    for result in (validate_record_ref(event.record_ref), validate_provenance(event.provenance), validate_workspace_boundary((event.record_ref,), event.workspace_id)):
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        rule_ids.extend(result.rule_ids)
    if event.event_type != B25_STATE_EVENT_TYPE:
        errors.append(f"event_type must be {B25_STATE_EVENT_TYPE}")
    for label, value, validator in (
        ("previous_status", event.previous_status, validate_status),
        ("next_status", event.next_status, validate_status),
        ("previous_tier", event.previous_tier, validate_tier),
        ("next_tier", event.next_tier, validate_tier),
    ):
        if value is not None:
            result = validator(value)
            errors.extend(f"{label}: {error}" for error in result.errors)
            warnings.extend(result.warnings)
            rule_ids.extend(result.rule_ids)
    if errors:
        return validation_fail(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(rule_ids)), tuple(dict.fromkeys(warnings)))
    return validation_pass(tuple(dict.fromkeys(rule_ids)))

def governance_state_event_to_dict(event: GovernanceStateEventContract) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "workspace_id": event.workspace_id,
        "record_ref": {
            "record_id": event.record_ref.record_id,
            "record_type": event.record_ref.record_type,
            "workspace_id": event.record_ref.workspace_id,
            "content_id": event.record_ref.content_id,
            "source_ref": event.record_ref.source_ref,
        },
        "provenance": {
            "source_type": event.provenance.source_type,
            "source_id": event.provenance.source_id,
            "source_label": event.provenance.source_label,
            "created_by": event.provenance.created_by,
            "trace_id": event.provenance.trace_id,
            "created_at": event.provenance.created_at,
            "metadata": dict(event.provenance.metadata or {}),
        },
        "previous_status": event.previous_status,
        "next_status": event.next_status,
        "previous_tier": event.previous_tier,
        "next_tier": event.next_tier,
        "event_reason": event.event_reason,
        "limitations": list(event.limitations),
        "non_claims": list(event.non_claims),
        "mode": event.mode,
    }

def data_only_event_capability() -> Mapping[str, object]:
    return {
        "capability": "b25_governance_state_event_contract",
        "input_scope": "caller_supplied_payload_only",
        "requires_db": False,
        "requires_provider": False,
        "requires_private_context_brain": False,
        "mutates_state": False,
        "limitations": list(B25_LIMITATIONS),
        "non_claims": list(B25_NON_CLAIMS),
    }
