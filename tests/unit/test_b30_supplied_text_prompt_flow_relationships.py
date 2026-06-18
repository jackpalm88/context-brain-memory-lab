from pathlib import Path

from memory_lab.reasoning.ingestion_prompt_flow import (
    B30_LIMITATIONS,
    B30_NON_CLAIMS,
    SuppliedTextPromptFlowRequest,
    build_prompt_request_from_supplied_text,
)
from memory_lab.reasoning.llm_executor import LLMExecutionRequest
from memory_lab.reasoning.prompt_package import PromptPackage

WORKSPACE = "550e8400-e29b-41d4-a716-446655440000"
TEXT = "B30 composes prior public safe contract milestones into a bounded prompt request shape. " * 8


def _request(**kwargs):
    values = dict(
        workspace_id=WORKSPACE,
        content_id="b30-relationships",
        text=TEXT,
        title="B30 relationships",
        metadata={"domain": "contracts"},
        query="compose milestones",
        purpose="relationship proof",
    )
    values.update(kwargs)
    return SuppliedTextPromptFlowRequest(**values)


def test_b30_composes_b27_b28_b29_b23_and_b22_request_shape():
    result = build_prompt_request_from_supplied_text(_request())

    assert result.ok is True
    assert result.ingestion_result.mode == "b27_public_safe_ingestion_pipeline_contract_v1"
    assert result.prompt_handoff.mode == "b29_public_safe_persisted_records_to_prompt_package_handoff_v1"
    assert result.prompt_handoff.context_handoff.mode == "b28_public_safe_persistence_to_retrieval_handoff_v1"
    assert isinstance(result.prompt_package, PromptPackage)
    assert isinstance(result.llm_request, LLMExecutionRequest)
    assert result.llm_request.live_mode_enabled is False
    assert result.llm_request.backend_name == "none"


def test_b30_does_not_replace_b23_b27_b28_or_b29_logic():
    result = build_prompt_request_from_supplied_text(_request())

    assert result.ok is True
    assert result.ingestion_result.request_id.startswith("b27-")
    assert result.prompt_handoff.prompt_package is result.prompt_package
    assert result.prompt_handoff.context_handoff.context_package is not None
    assert result.prompt_package.evidence_ids == result.prompt_handoff.prompt_package.evidence_ids


def test_b30_does_not_execute_b22_request():
    result = build_prompt_request_from_supplied_text(_request())

    assert result.ok is True
    assert result.llm_request is not None
    assert result.llm_request.live_mode_enabled is False
    assert result.llm_request.allow_fake_backend is False
    assert result.llm_request.backend_name == "none"
    assert "not_llm_execution" in result.non_claims


def test_b30_does_not_modify_or_require_wrapper_descriptors_or_docs_alignment():
    source = Path("memory_lab/reasoning/ingestion_prompt_flow.py").read_text(encoding="utf-8")
    runtime_surface = "\n".join(line for line in source.splitlines() if "no_wrapper_descriptor_update" not in line and "not_wrapper_descriptor_update" not in line)

    assert "memory_lab.wrappers" not in source
    assert "wrapper_descriptor" not in runtime_surface
    assert "docs/CAPABILITIES" not in source
    assert "not_wrapper_descriptor_update" in B30_NON_CLAIMS
    assert "not_docs_capabilities_alignment" in B30_NON_CLAIMS
    assert "no_wrapper_descriptor_update" in B30_LIMITATIONS


def test_b30_does_not_create_live_ingestion_runtime_or_runtime_exposure():
    source = Path("memory_lab/reasoning/ingestion_prompt_flow.py").read_text(encoding="utf-8")
    runtime_surface = "\n".join(line for line in source.splitlines() if "mcp" not in line.lower())

    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "MCP" not in runtime_surface
    assert "execute_llm_request" not in source
    assert "not_live_ingestion_runtime" in B30_NON_CLAIMS
    assert "not_api_or_mcp_runtime" in B30_NON_CLAIMS
