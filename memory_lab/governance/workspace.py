"""B25 caller-supplied workspace boundary validation.

The helpers in this module validate supplied identifiers only. They do not look up tenants, enforce auth, call APIs, or mutate storage.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, Mapping, Sequence

from memory_lab.governance.state import GovernanceValidationResult, validation_fail, validation_pass

def validate_workspace_id(workspace_id: str | None) -> GovernanceValidationResult:
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        return validation_fail(("workspace_id is required",), ("B25-WORKSPACE-REQUIRED",))
    return validation_pass(("B25-WORKSPACE-REQUIRED", "B25-WORKSPACE-CALLER-SUPPLIED"))

def validate_workspace_boundary(records: Sequence[Any], workspace_id: str | None = None) -> GovernanceValidationResult:
    records = tuple(records or ())
    context_check = validate_workspace_id(workspace_id) if workspace_id is not None else None
    if context_check is not None and not context_check.valid:
        return context_check
    found: list[str] = []
    errors: list[str] = []
    for index, record in enumerate(records):
        extracted = _workspace_from_record(record)
        if not isinstance(extracted, str) or not extracted.strip():
            errors.append(f"record[{index}] workspace_id is required")
            continue
        normalized = extracted.strip()
        found.append(normalized)
        if workspace_id is not None and normalized != workspace_id.strip():
            errors.append(f"record[{index}] workspace_id does not match explicit workspace context")
    unique = tuple(dict.fromkeys(found))
    if len(unique) > 1:
        errors.append("mixed workspace_ids are not allowed")
    if not records and workspace_id is None:
        errors.append("at least one record or explicit workspace_id is required")
    if errors:
        return validation_fail(errors, ("B25-WORKSPACE-BOUNDARY", "B25-NO-LIVE-TENANT-LOOKUP"))
    return validation_pass(("B25-WORKSPACE-BOUNDARY", "B25-NO-LIVE-TENANT-LOOKUP"))

def assert_same_workspace(records: Sequence[Any]) -> GovernanceValidationResult:
    return validate_workspace_boundary(records)

def _workspace_from_record(record: Any) -> str | None:
    if isinstance(record, Mapping):
        if "workspace_id" in record:
            return _as_str_or_none(record.get("workspace_id"))
        ref = record.get("record_ref")
        if isinstance(ref, Mapping):
            return _as_str_or_none(ref.get("workspace_id"))
    if hasattr(record, "workspace_id"):
        return _as_str_or_none(getattr(record, "workspace_id"))
    if hasattr(record, "record_ref"):
        ref = getattr(record, "record_ref")
        if hasattr(ref, "workspace_id"):
            return _as_str_or_none(getattr(ref, "workspace_id"))
        if is_dataclass(ref) and hasattr(ref, "workspace_id"):
            return _as_str_or_none(getattr(ref, "workspace_id"))
    return None

def _as_str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
