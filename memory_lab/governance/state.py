"""B25 data-only governance state contracts.

This module defines deterministic public-safe state primitives over caller-supplied values.
It does not perform storage mutation, service calls, provider calls, tenant lookup, or private memory access.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

B25_GOVERNANCE_STATE_MODE = "b25_data_only_governance_state_workspace_boundary_v1"
B25_LIMITATIONS: tuple[str, ...] = (
    "caller_supplied_input_only",
    "deterministic_public_safe_validation_only",
    "data_only_governance_state_contract",
    "no_storage_mutation",
    "no_db_access",
    "no_provider_call",
    "no_private_context_brain_access",
    "no_live_tenant_lookup",
    "no_auth_or_rbac_enforcement",
    "not_api_runtime",
    "not_production_governance_runtime",
)
B25_NON_CLAIMS: tuple[str, ...] = (
    "not_production_ready",
    "not_db_backed_persistence",
    "not_live_governance_lifecycle",
    "not_full_context_brain_parity",
    "not_private_context_brain_parity",
    "not_live_memory_retrieval",
    "not_provider_backed_intelligence",
    "not_mcp_or_gpt_actions_production_readiness",
)
GOVERNANCE_STATUSES: tuple[str, ...] = ("draft", "needs_review", "active", "archived", "superseded", "rejected")
GOVERNANCE_TIERS: tuple[str, ...] = ("discard", "transient", "probationary", "persistent", "decision_artifact", "archived", "conflicted", "superseded", "decayed")
STATUS_TRANSITIONS: Mapping[str | None, tuple[str, ...]] = {
    None: ("draft", "needs_review", "active", "rejected"),
    "draft": ("needs_review", "active", "rejected", "archived"),
    "needs_review": ("draft", "active", "rejected", "archived"),
    "active": ("superseded", "archived", "rejected"),
    "rejected": ("archived",),
    "superseded": ("archived",),
    "archived": (),
}

@dataclass(frozen=True)
class GovernanceValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = B25_LIMITATIONS
    non_claims: tuple[str, ...] = B25_NON_CLAIMS
    mode: str = B25_GOVERNANCE_STATE_MODE

@dataclass(frozen=True)
class GovernanceRecordRef:
    record_id: str
    record_type: str
    workspace_id: str
    content_id: str | None = None
    source_ref: str | None = None

@dataclass(frozen=True)
class GovernanceProvenance:
    source_type: str
    source_id: str
    source_label: str
    created_by: str
    trace_id: str
    created_at: str
    metadata: Mapping[str, Any] | None = None

@dataclass(frozen=True)
class GovernanceState:
    record_ref: GovernanceRecordRef
    status: str
    tier: str
    provenance: GovernanceProvenance
    supersedes: str | None = None
    superseded_by: str | None = None
    state_reason: str | None = None
    limitations: tuple[str, ...] = B25_LIMITATIONS
    non_claims: tuple[str, ...] = B25_NON_CLAIMS
    mode: str = B25_GOVERNANCE_STATE_MODE

def validation_pass(rule_ids: Sequence[str] = ()) -> GovernanceValidationResult:
    return GovernanceValidationResult(valid=True, rule_ids=_clean_tuple(rule_ids))

def validation_fail(errors: Sequence[str], rule_ids: Sequence[str] = (), warnings: Sequence[str] = ()) -> GovernanceValidationResult:
    return GovernanceValidationResult(valid=False, errors=_clean_tuple(errors), warnings=_clean_tuple(warnings), rule_ids=_clean_tuple(rule_ids))

def validate_status(status: str | None) -> GovernanceValidationResult:
    if not _has_text(status):
        return validation_fail(("status is required",), ("B25-STATUS-REQUIRED",))
    normalized = str(status).strip()
    if normalized not in GOVERNANCE_STATUSES:
        return validation_fail((f"invalid governance status: {normalized}",), ("B25-STATUS-ALLOWED",))
    return validation_pass(("B25-STATUS-ALLOWED",))

def validate_tier(tier: str | None) -> GovernanceValidationResult:
    if not _has_text(tier):
        return validation_fail(("tier is required",), ("B25-TIER-REQUIRED",))
    normalized = str(tier).strip()
    if normalized not in GOVERNANCE_TIERS:
        return validation_fail((f"invalid governance tier: {normalized}",), ("B25-TIER-ALLOWED",))
    return validation_pass(("B25-TIER-ALLOWED",))

def validate_record_ref(record_ref: GovernanceRecordRef) -> GovernanceValidationResult:
    errors: list[str] = []
    rules: list[str] = ["B25-RECORD-REF"]
    if not _has_text(record_ref.record_id):
        errors.append("record_id is required")
    if not _has_text(record_ref.record_type):
        errors.append("record_type is required")
    if not _has_text(record_ref.workspace_id):
        errors.append("workspace_id is required")
        rules.append("B25-WORKSPACE-REQUIRED")
    return validation_fail(errors, rules) if errors else validation_pass(rules)

def validate_provenance(provenance: GovernanceProvenance) -> GovernanceValidationResult:
    errors: list[str] = []
    rules: list[str] = ["B25-PROVENANCE-DATA-ONLY"]
    for field_name in ("source_type", "source_id", "source_label", "created_by", "trace_id", "created_at"):
        if not _has_text(getattr(provenance, field_name)):
            errors.append(f"{field_name} is required")
    return validation_fail(errors, rules) if errors else validation_pass(rules)

def validate_governance_state(state: GovernanceState) -> GovernanceValidationResult:
    checks = (validate_record_ref(state.record_ref), validate_status(state.status), validate_tier(state.tier), validate_provenance(state.provenance))
    return _merge_results(checks, default_rule_ids=("B25-GOVERNANCE-STATE",))

def validate_status_transition(previous_status: str | None, next_status: str) -> GovernanceValidationResult:
    next_check = validate_status(next_status)
    if not next_check.valid:
        return next_check
    if previous_status is not None:
        previous_check = validate_status(previous_status)
        if not previous_check.valid:
            return previous_check
    previous_key = previous_status.strip() if isinstance(previous_status, str) else None
    next_key = next_status.strip()
    allowed = STATUS_TRANSITIONS.get(previous_key, ())
    if next_key not in allowed:
        return validation_fail((f"status transition not allowed: {previous_key!r} -> {next_key!r}",), ("B25-STATUS-TRANSITION",))
    return validation_pass(("B25-STATUS-TRANSITION",))

def with_validation_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.setdefault("limitations", list(B25_LIMITATIONS))
    out.setdefault("non_claims", list(B25_NON_CLAIMS))
    out.setdefault("mode", B25_GOVERNANCE_STATE_MODE)
    return out

def ensure_state_valid(state: GovernanceState) -> GovernanceState:
    result = validate_governance_state(state)
    if not result.valid:
        raise ValueError("; ".join(result.errors))
    return replace(state)

def _merge_results(results: Sequence[GovernanceValidationResult], default_rule_ids: Sequence[str] = ()) -> GovernanceValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    rules: list[str] = list(default_rule_ids)
    for result in results:
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        rules.extend(result.rule_ids)
    if errors:
        return validation_fail(_dedupe(errors), _dedupe(rules), _dedupe(warnings))
    return GovernanceValidationResult(valid=True, warnings=_dedupe(warnings), rule_ids=_dedupe(rules))

def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())

def _clean_tuple(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(value) for value in values if str(value).strip())

def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)
