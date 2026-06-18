from pathlib import Path

from memory_lab.reasoning.ingestion_prompt_flow import (
    B30_LIMITATIONS,
    B30_NON_CLAIMS,
    SuppliedTextPromptFlowCapabilityMetadata,
    SuppliedTextPromptFlowRequest,
    build_prompt_package_from_supplied_text,
)

WORKSPACE = "550e8400-e29b-41d4-a716-446655440000"
MODULE = Path("memory_lab/reasoning/ingestion_prompt_flow.py")


def _source():
    return MODULE.read_text(encoding="utf-8")


def test_runtime_safety_scan_for_b30_production_module():
    source = _source()
    runtime_surface = "\n".join(
        line for line in source.splitlines()
        if "B30_LIMITATIONS" not in line
        and "B30_NON_CLAIMS" not in line
        and "uses_vector_db" not in line
        and "no_vector_db_access" not in line
        and "not_embedding_or_vector_retrieval" not in line
    )
    forbidden = (
        "DATABASE_URL",
        "os.environ",
        "psycopg",
        "sqlalchemy",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "openai",
        "anthropic",
        "Provider",
        "vector_db",
        "MCP server",
        "FastAPI",
        "APIRouter",
        "Depends",
        "migrations",
        "alembic",
        "execute_llm_request",
        "complete_",
    )
    for token in forbidden:
        assert token not in runtime_surface


def test_no_runtime_imports_or_wrapper_descriptor_updates():
    source = _source()
    assert "memory_lab.api" not in source
    assert "memory_lab.mcp" not in source
    assert "memory_lab.providers" not in source
    assert "memory_lab.wrappers" not in source
    assert "memory_lab.retrieval.persistence_handoff import" not in source
    assert "memory_lab.persistence.memory_backend" not in source


def test_explicit_non_claims_are_complete():
    required = {
        "not_production_ready",
        "not_live_memory_retrieval",
        "not_semantic_search",
        "not_db_backed_retrieval",
        "not_db_backed_production_persistence",
        "not_live_ingestion_runtime",
        "not_provider_backed_reasoning",
        "not_llm_execution",
        "not_embedding_or_vector_retrieval",
        "not_private_context_brain_parity",
        "not_full_context_brain_parity",
        "not_api_or_mcp_runtime",
        "not_mcp_or_gpt_actions_production_ready",
        "not_prompt_quality_or_truth_claim",
        "not_wrapper_descriptor_update",
        "not_docs_capabilities_alignment",
    }
    assert required.issubset(set(B30_NON_CLAIMS))


def test_false_capability_metadata_remains_false():
    metadata = SuppliedTextPromptFlowCapabilityMetadata()
    assert metadata.live_backend_used is False
    assert metadata.requires_db is False
    assert metadata.requires_provider is False
    assert metadata.requires_private_context_brain is False
    assert metadata.uses_embeddings is False
    assert metadata.uses_vector_db is False
    assert metadata.executes_llm is False
    assert metadata.production_runtime is False
    assert metadata.mutates_external_state is False
    assert metadata.api_runtime is False
    assert metadata.mcp_runtime is False
    assert metadata.supplied_backend_write_possible is True
    assert metadata.external_state_mutation is False
    assert metadata.db_persistence is False


def test_non_claims_and_metadata_are_present_on_success_and_failure():
    success = build_prompt_package_from_supplied_text(
        SuppliedTextPromptFlowRequest(
            workspace_id=WORKSPACE,
            content_id="b30-public-safe",
            text="Public safe evidence package construction over supplied text. " * 8,
        )
    )
    failure = build_prompt_package_from_supplied_text(
        SuppliedTextPromptFlowRequest(workspace_id=" ", content_id="b30-public-safe", text="text")
    )

    assert success.ok is True
    assert failure.ok is False
    assert success.capability_metadata.requires_db is False
    assert failure.capability_metadata.requires_db is False
    assert "not_production_ready" in success.non_claims
    assert "not_production_ready" in failure.non_claims
    assert "no_wrapper_descriptor_update" in B30_LIMITATIONS
    assert "no_docs_capabilities_alignment" in B30_LIMITATIONS


def test_claim_scan_rejects_affirmative_runtime_claims():
    source = _source().lower()
    forbidden_phrases = (
        "production ready",
        "production retrieval runtime",
        "live memory retrieval",
        "live semantic search",
        "searches context brain",
        "full context brain ready",
        "db-backed retrieval",
        "provider-backed reasoning",
        "executed llm reasoning",
        "generated embeddings",
        "vector search",
        "mcp production ready",
        "gpt actions production ready",
        "wrapper descriptor update completed",
        "docs/capabilities alignment completed",
    )
    for phrase in forbidden_phrases:
        assert phrase not in source
