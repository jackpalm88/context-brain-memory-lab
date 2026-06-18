from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend
from memory_lab.persistence.results import PersistenceResult
from memory_lab.reasoning.ingestion_prompt_flow import (
    B30_PROMPT_FLOW_MODE,
    PublicSafeSuppliedTextPromptFlow,
    SuppliedTextPromptFlowRequest,
    build_prompt_package_from_supplied_text,
    build_prompt_request_from_supplied_text,
)
from memory_lab.reasoning.prompt_package import PromptPackage

WORKSPACE = "550e8400-e29b-41d4-a716-446655440000"
TEXT = "Governed memory systems need public safe evidence packaging and bounded prompt request construction. " * 8


def _request(**kwargs):
    values = dict(
        workspace_id=WORKSPACE,
        content_id="b30-direct-record",
        text=TEXT,
        title="B30 direct supplied text",
        source_ref="caller-supplied-note",
        metadata={"domain": "ai_engineering", "source_type": "note"},
        query="governed memory prompt request",
        purpose="package supplied evidence",
        max_context_chars=1200,
        snippet_chars=180,
    )
    values.update(kwargs)
    return SuppliedTextPromptFlowRequest(**values)


def test_direct_supplied_text_flow_builds_prompt_package_and_b22_request_shape():
    result = build_prompt_request_from_supplied_text(_request())

    assert result.ok is True
    assert result.status == "completed_with_prompt_package_and_llm_request_shape"
    assert result.mode == B30_PROMPT_FLOW_MODE
    assert result.ingestion_result is not None
    assert result.ingestion_result.mode == "b27_public_safe_ingestion_pipeline_contract_v1"
    assert result.persistence_record is not None
    assert result.persistence_record.content_id == "b30-direct-record"
    assert result.persistence_record.workspace_id == WORKSPACE
    assert result.persistence_record.metadata["b30_mode"] == B30_PROMPT_FLOW_MODE
    assert result.prompt_handoff is not None
    assert result.prompt_handoff.mode == "b29_public_safe_persisted_records_to_prompt_package_handoff_v1"
    assert isinstance(result.prompt_package, PromptPackage)
    assert result.llm_request is not None
    assert result.llm_request.live_mode_enabled is False
    assert result.llm_request.backend_name == "none"
    assert result.llm_request.allow_fake_backend is False
    assert result.llm_request.evidence_count == len(result.prompt_package.evidence_ids)
    assert "not_llm_execution" in result.non_claims
    assert "no_llm_execution" in result.limitations


def test_prompt_package_helper_does_not_return_llm_request_shape():
    result = build_prompt_package_from_supplied_text(_request())

    assert result.ok is True
    assert result.status == "completed_with_prompt_package"
    assert isinstance(result.prompt_package, PromptPackage)
    assert result.llm_request is None


def test_deterministic_output_for_identical_input_and_bounded_prompt_context():
    first = build_prompt_request_from_supplied_text(_request())
    second = build_prompt_request_from_supplied_text(_request())

    assert first.ok and second.ok
    assert first.request_id == second.request_id
    assert first.ingestion_result.request_id == second.ingestion_result.request_id
    assert first.prompt_package.evidence_ids == second.prompt_package.evidence_ids
    assert first.status == second.status
    assert len(first.prompt_package.prompt) <= 2200


def test_supplied_backend_mode_writes_only_when_explicitly_requested_and_reads_through_backend():
    backend = InMemoryPersistenceBackend()
    result = build_prompt_request_from_supplied_text(
        _request(
            content_id="b30-backend-record",
            backend=backend,
            use_supplied_backend=True,
            persist_to_supplied_backend=True,
        )
    )

    assert result.ok is True
    assert result.status == "completed_with_prompt_package_and_llm_request_shape"
    assert result.ingestion_result.persistence["attempted"] is True
    assert result.prompt_handoff.context_handoff is not None
    assert result.prompt_handoff.context_handoff.context_package is not None
    listed = backend.list_content_records(WORKSPACE)
    assert listed.ok is True
    assert len(listed.value) == 1
    assert listed.value[0].content_id == "b30-backend-record"


def test_backend_is_not_mutated_unless_persist_to_supplied_backend_is_requested():
    backend = InMemoryPersistenceBackend()
    result = build_prompt_request_from_supplied_text(_request(backend=backend, use_supplied_backend=False, persist_to_supplied_backend=False))

    assert result.ok is True
    listed = backend.list_content_records(WORKSPACE)
    assert listed.ok is True
    assert listed.value == ()


def test_supplied_backend_mode_requires_backend_when_selected():
    result = build_prompt_request_from_supplied_text(_request(use_supplied_backend=True, persist_to_supplied_backend=False, backend=None))

    assert result.ok is False
    assert result.status == "persistence_backend_required"
    assert result.errors[0].code == "persistence_backend_required"


class FailingPutBackend:
    def put_content_record(self, record):
        return PersistenceResult.failure("put_content_record", "backend_unavailable", "supplied backend failed", "backend")


def test_supplied_backend_failure_is_structured():
    result = build_prompt_request_from_supplied_text(
        _request(backend=FailingPutBackend(), use_supplied_backend=True, persist_to_supplied_backend=True)
    )

    assert result.ok is False
    assert result.status == "persistence_backend_failed"
    assert result.errors[0].code == "persistence_backend_failed"


def test_class_entrypoint_exposes_expected_name_and_mode():
    flow = PublicSafeSuppliedTextPromptFlow()

    assert flow.name == "PublicSafeSuppliedTextPromptFlow"
    assert flow.mode == B30_PROMPT_FLOW_MODE
