from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend
from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult
from memory_lab.reasoning.ingestion_prompt_flow import SuppliedTextPromptFlowRequest, build_prompt_request_from_supplied_text

WORKSPACE = "550e8400-e29b-41d4-a716-446655440000"
OTHER_WORKSPACE = "550e8400-e29b-41d4-a716-446655440001"
TEXT = "Workspace boundaries must prevent cross workspace evidence leakage in public safe supplied text flows. " * 8


def _request(**kwargs):
    values = dict(
        workspace_id=WORKSPACE,
        content_id="b30-boundary",
        text=TEXT,
        title="B30 boundary",
        query="workspace evidence",
        purpose="prove boundary",
    )
    values.update(kwargs)
    return SuppliedTextPromptFlowRequest(**values)


def test_invalid_workspace_is_rejected_before_prompt_packaging():
    result = build_prompt_request_from_supplied_text(_request(workspace_id=" "))

    assert result.ok is False
    assert result.status == "invalid_workspace"
    assert result.errors[0].code == "invalid_workspace"
    assert result.prompt_package is None
    assert result.llm_request is None


def test_missing_text_and_content_id_are_structured_errors():
    missing_text = build_prompt_request_from_supplied_text(_request(text="   "))
    missing_content = build_prompt_request_from_supplied_text(_request(content_id=""))

    assert missing_text.ok is False
    assert missing_text.status == "missing_text"
    assert missing_text.errors[0].code == "missing_text"
    assert missing_content.ok is False
    assert missing_content.status == "missing_content_id"
    assert missing_content.errors[0].code == "missing_content_id"


class CrossWorkspaceListBackend:
    def put_content_record(self, record):
        return PersistenceResult.success("put_content_record", record)

    def list_content_records(self, workspace_id):
        return PersistenceResult.success(
            "list_content_records",
            (
                ContentPersistenceRecord(
                    content_id="leaked-record",
                    workspace_id=OTHER_WORKSPACE,
                    text="This record belongs to another workspace and must not become evidence.",
                    title="other",
                ),
            ),
        )


def test_mismatched_workspace_records_from_backend_are_rejected():
    result = build_prompt_request_from_supplied_text(
        _request(backend=CrossWorkspaceListBackend(), use_supplied_backend=True, persist_to_supplied_backend=True)
    )

    assert result.ok is False
    assert result.status == "boundary_violation"
    assert result.errors[0].code == "boundary_violation"
    assert result.prompt_package is None
    assert result.llm_request is None


def test_no_cross_workspace_evidence_leakage_from_supplied_backend_listing():
    backend = InMemoryPersistenceBackend()
    backend.put_content_record(ContentPersistenceRecord(content_id="other", workspace_id=OTHER_WORKSPACE, text="other workspace text"))
    result = build_prompt_request_from_supplied_text(
        _request(backend=backend, use_supplied_backend=True, persist_to_supplied_backend=True, content_id="own-record")
    )

    assert result.ok is True
    assert result.prompt_package is not None
    assert "own-record" in result.prompt_package.prompt
    assert "other workspace text" not in result.prompt_package.prompt


def test_direct_record_mode_preserves_b25_b27_b28_b29_boundary_behavior():
    result = build_prompt_request_from_supplied_text(_request())

    assert result.ok is True
    assert result.ingestion_result.workspace_id == WORKSPACE
    assert result.persistence_record.workspace_id == WORKSPACE
    assert result.prompt_handoff.workspace_id == WORKSPACE
    assert result.prompt_handoff.context_handoff.workspace_id == WORKSPACE
