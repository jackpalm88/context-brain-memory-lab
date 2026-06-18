from pathlib import Path

from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.reasoning import persistence_prompt_handoff as module
from memory_lab.reasoning.llm_executor import LLMExecutionRequest, plan_llm_execution
from memory_lab.reasoning.persistence_prompt_handoff import (
    PersistencePromptPackageRequest,
    PublicSafePersistencePromptPackageHandoff,
    build_llm_execution_request_from_persisted_records,
)


SOURCE = Path(module.__file__).read_text(encoding="utf-8")


def _record():
    return ContentPersistenceRecord(
        content_id="b22-shape",
        workspace_id="ws-a",
        text="b22 compatible prompt handoff evidence",
        title="B22 Shape",
        metadata={"domain": "reasoning", "tags": ("b22", "prompt")},
    )


def test_builds_b22_compatible_llm_execution_request_shape_without_live_execution():
    result = build_llm_execution_request_from_persisted_records((_record(),), workspace_id="ws-a", query="b22 shape")

    assert result.ok is True
    assert result.prompt_package is not None
    assert isinstance(result.llm_request, LLMExecutionRequest)
    assert result.llm_request.prompt == result.prompt_package.prompt
    assert result.llm_request.system == result.prompt_package.system
    assert result.llm_request.expected_schema == result.prompt_package.expected_schema
    assert result.llm_request.live_mode_enabled is False
    assert result.llm_request.backend_name == "none"
    assert result.llm_request.allow_fake_backend is False
    assert result.llm_request.evidence_count == len(result.prompt_package.evidence_ids)
    assert result.llm_request.metadata["b29_mode"] == module.B29_PROMPT_HANDOFF_MODE


def test_b22_plan_remains_blocked_with_generated_request_shape_and_no_backend_required():
    result = build_llm_execution_request_from_persisted_records((_record(),), workspace_id="ws-a", query="b22 shape")

    plan = plan_llm_execution(result.llm_request)

    assert plan.should_execute is False
    assert plan.backend_name == "none"
    assert plan.blocked_reason == "live_mode_disabled"
    assert plan.uses_live_provider is False
    assert plan.requires_provider_config is False


def test_class_interface_can_request_b22_shape_without_executing():
    request = PersistencePromptPackageRequest(workspace_id="ws-a", records=(_record(),), query="b22", include_llm_request=True)

    result = PublicSafePersistencePromptPackageHandoff().build_llm_execution_request(request)

    assert result.ok is True
    assert result.status == "completed_with_prompt_package_and_llm_request_shape"
    assert result.llm_request is not None
    assert result.llm_request.live_mode_enabled is False


def test_b29_module_does_not_import_or_call_b22_execution_helper():
    assert "execute_llm_request" not in SOURCE
    assert "complete_" not in SOURCE
