"""B26 deterministic in-memory persistence backend for tests.

This backend stores only caller-supplied objects in process memory. It is a test
adapter for the B26 contract and does not interact with any external backend.
"""
from __future__ import annotations

from dataclasses import is_dataclass, replace
from typing import Any, Mapping

from memory_lab.governance.state import GovernanceState, validate_governance_state
from memory_lab.governance.state_events import GovernanceStateEventContract, validate_governance_state_event_contract
from memory_lab.governance.workspace import validate_workspace_boundary, validate_workspace_id
from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult

class InMemoryPersistenceBackend:
    """Deterministic workspace-scoped in-memory implementation for unit tests."""

    def __init__(self) -> None:
        self._content_records: dict[tuple[str, str], Any] = {}
        self._governance_states: dict[tuple[str, str], GovernanceState] = {}
        self._governance_events: dict[tuple[str, str], tuple[GovernanceStateEventContract, ...]] = {}

    def put_content_record(self, record: ContentPersistenceRecord | Any) -> PersistenceResult:
        workspace_id = _field_value(record, "workspace_id")
        content_id = _field_value(record, "content_id") or _field_value(record, "record_id")
        check = _validate_required_id(workspace_id, "workspace_id", "put_content_record")
        if check is not None:
            return check
        check = _validate_required_id(content_id, "content_id", "put_content_record")
        if check is not None:
            return check
        key = (str(workspace_id).strip(), str(content_id).strip())
        self._content_records[key] = _stable_copy(record)
        return PersistenceResult.success("put_content_record", self._content_records[key])

    def get_content_record(self, workspace_id: str, content_id: str) -> PersistenceResult:
        check = _validate_required_id(workspace_id, "workspace_id", "get_content_record")
        if check is not None:
            return check
        check = _validate_required_id(content_id, "content_id", "get_content_record")
        if check is not None:
            return check
        key = (workspace_id.strip(), content_id.strip())
        if key not in self._content_records:
            return PersistenceResult.failure("get_content_record", "not_found", "content record not found", "content_id")
        return PersistenceResult.success("get_content_record", self._content_records[key])

    def list_content_records(self, workspace_id: str) -> PersistenceResult:
        check = validate_workspace_id(workspace_id)
        if not check.valid:
            return PersistenceResult.failure("list_content_records", "invalid_workspace", "; ".join(check.errors), "workspace_id")
        records = tuple(value for (ws, _), value in sorted(self._content_records.items()) if ws == workspace_id.strip())
        return PersistenceResult.success("list_content_records", records)

    def put_governance_state(self, state: GovernanceState) -> PersistenceResult:
        result = validate_governance_state(state)
        if not result.valid:
            return PersistenceResult.failure("put_governance_state", "invalid_governance_state", "; ".join(result.errors))
        key = (state.record_ref.workspace_id.strip(), state.record_ref.record_id.strip())
        self._governance_states[key] = replace(state)
        return PersistenceResult.success("put_governance_state", self._governance_states[key])

    def get_governance_state(self, workspace_id: str, record_id: str) -> PersistenceResult:
        check = _validate_required_id(workspace_id, "workspace_id", "get_governance_state")
        if check is not None:
            return check
        check = _validate_required_id(record_id, "record_id", "get_governance_state")
        if check is not None:
            return check
        key = (workspace_id.strip(), record_id.strip())
        if key not in self._governance_states:
            return PersistenceResult.failure("get_governance_state", "not_found", "governance state not found", "record_id")
        return PersistenceResult.success("get_governance_state", self._governance_states[key])

    def append_governance_event(self, event: GovernanceStateEventContract) -> PersistenceResult:
        result = validate_governance_state_event_contract(event)
        if not result.valid:
            return PersistenceResult.failure("append_governance_event", "invalid_governance_event", "; ".join(result.errors))
        boundary = validate_workspace_boundary((event.record_ref,), event.workspace_id)
        if not boundary.valid:
            return PersistenceResult.failure("append_governance_event", "workspace_boundary_violation", "; ".join(boundary.errors), "workspace_id")
        key = (event.workspace_id.strip(), event.record_ref.record_id.strip())
        self._governance_events[key] = self._governance_events.get(key, ()) + (event,)
        return PersistenceResult.success("append_governance_event", event)

    def list_governance_events(self, workspace_id: str, record_id: str | None = None) -> PersistenceResult:
        check = validate_workspace_id(workspace_id)
        if not check.valid:
            return PersistenceResult.failure("list_governance_events", "invalid_workspace", "; ".join(check.errors), "workspace_id")
        ws = workspace_id.strip()
        if record_id is not None:
            if not str(record_id).strip():
                return PersistenceResult.failure("list_governance_events", "invalid_record_id", "record_id is required", "record_id")
            events = self._governance_events.get((ws, str(record_id).strip()), ())
            return PersistenceResult.success("list_governance_events", events)
        out: list[GovernanceStateEventContract] = []
        for (event_workspace, _), events in sorted(self._governance_events.items()):
            if event_workspace == ws:
                out.extend(events)
        return PersistenceResult.success("list_governance_events", tuple(out))


def _validate_required_id(value: object, field_name: str, operation: str) -> PersistenceResult | None:
    if not isinstance(value, str) or not value.strip():
        return PersistenceResult.failure(operation, f"invalid_{field_name}", f"{field_name} is required", field_name)
    return None


def _field_value(record: Any, field_name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(field_name)
    return getattr(record, field_name, None)


def _stable_copy(record: Any) -> Any:
    if isinstance(record, ContentPersistenceRecord):
        return replace(record, metadata=dict(record.metadata))
    if isinstance(record, Mapping):
        return dict(record)
    if is_dataclass(record):
        return replace(record)
    return record
