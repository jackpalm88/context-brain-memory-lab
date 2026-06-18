from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult
from memory_lab.reasoning.persistence_prompt_handoff import build_prompt_package_from_persisted_records


def _record(content_id="a", workspace_id="ws-a"):
    return ContentPersistenceRecord(
        content_id=content_id,
        workspace_id=workspace_id,
        text="workspace scoped prompt evidence",
        title="Workspace",
        metadata={"domain": "docs"},
    )


def test_invalid_workspace_is_blocked_before_prompt_package_creation():
    result = build_prompt_package_from_persisted_records((_record(workspace_id="ws-a"),), workspace_id="")

    assert result.ok is False
    assert result.status == "invalid_workspace"
    assert result.errors[0].code == "invalid_workspace"
    assert result.errors[0].field == "workspace_id"
    assert result.prompt_package is None


def test_cross_workspace_supplied_record_returns_boundary_violation():
    result = build_prompt_package_from_persisted_records((_record(workspace_id="ws-b"),), workspace_id="ws-a")

    assert result.ok is False
    assert result.status == "boundary_violation"
    assert result.errors[0].code == "boundary_violation"
    assert result.errors[0].field == "workspace_id"
    assert result.prompt_package is None


class ListingBackend:
    def __init__(self):
        self.list_calls = []
        self.put_calls = []

    def list_content_records(self, workspace_id):
        self.list_calls.append(workspace_id)
        return PersistenceResult.success("list_content_records", (_record("from-backend", workspace_id=workspace_id),))

    def put_content_record(self, record):
        self.put_calls.append(record)
        raise AssertionError("B29 must not mutate a supplied backend")


class FailingBackend:
    def __init__(self):
        self.list_calls = []
        self.put_calls = []

    def list_content_records(self, workspace_id):
        self.list_calls.append(workspace_id)
        return PersistenceResult.failure("list_content_records", "boom", "backend failed", "backend")

    def put_content_record(self, record):
        self.put_calls.append(record)
        raise AssertionError("B29 must not mutate a supplied backend")


def test_supplied_backend_uses_b26_list_content_records_only():
    backend = ListingBackend()

    result = build_prompt_package_from_persisted_records((), workspace_id="ws-a", backend=backend, use_backend=True, query="backend")

    assert result.ok is True
    assert backend.list_calls == ["ws-a"]
    assert backend.put_calls == []
    assert result.context_handoff.candidates[0].item_id == "from-backend"
    assert "workspace scoped prompt evidence" in result.prompt_package.prompt


def test_backend_required_without_backend_when_backend_mode_requested():
    result = build_prompt_package_from_persisted_records((), workspace_id="ws-a", use_backend=True)

    assert result.ok is False
    assert result.status == "backend_required"
    assert result.errors[0].code == "backend_required"
    assert result.errors[0].field == "backend"
    assert result.prompt_package is None


def test_backend_result_failed_is_structured_and_has_no_mutation():
    backend = FailingBackend()

    result = build_prompt_package_from_persisted_records((), workspace_id="ws-a", backend=backend, use_backend=True)

    assert result.ok is False
    assert result.status == "backend_result_failed"
    assert result.errors[0].code == "backend_result_failed"
    assert result.errors[0].message == "backend failed"
    assert backend.list_calls == ["ws-a"]
    assert backend.put_calls == []
