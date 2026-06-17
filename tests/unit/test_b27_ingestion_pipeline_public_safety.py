from pathlib import Path

from memory_lab.ingestion import pipeline_contract
from memory_lab.ingestion.pipeline_contract import B27_LIMITATIONS, B27_NON_CLAIMS, IngestionPipelineRequest, run_ingestion_pipeline


IMPLEMENTATION_SOURCE = Path(pipeline_contract.__file__).read_text()


def test_no_provider_db_or_runtime_imports_in_pipeline_contract():
    forbidden = (
        "import requests",
        "import httpx",
        "import openai",
        "import anthropic",
        "create_engine",
        "psycopg",
        "sqlite",
        "FastAPI",
        "APIRouter",
        "FastMCP",
        "os.environ",
        "DATABASE_URL",
    )
    for pattern in forbidden:
        assert pattern not in IMPLEMENTATION_SOURCE


def test_no_url_fetching_http_content_retrieval_or_api_runtime_wiring():
    assert "source_ref_is_metadata_only_and_not_fetched" in B27_LIMITATIONS
    assert "no_api_or_auth_runtime" in B27_LIMITATIONS
    assert "no_mcp_or_gpt_actions_runtime_wiring" in B27_LIMITATIONS
    assert ".get(" not in IMPLEMENTATION_SOURCE or "requests" not in IMPLEMENTATION_SOURCE


def test_no_embeddings_vector_retrieval_or_live_private_claims():
    result = run_ingestion_pipeline(
        IngestionPipelineRequest(
            workspace_id="workspace-safety",
            content_id="safety-content",
            text="Caller supplied governance text for deterministic quality scoring and public-safe boundaries.",
        )
    )
    assert result.ok
    assert "no_embedding_or_vector_retrieval" in result.limitations
    assert "not_live_memory_retrieval" in result.non_claims
    assert "not_semantic_search" in result.non_claims
    assert "not_private_context_brain_parity" in result.non_claims
    assert "not_provider_backed_reasoning" in result.non_claims


def test_no_forbidden_affirmative_production_or_private_claims():
    forbidden_affirmative = (
        "production ready",
        "DB-backed ingestion",
        "Full Context Brain ready",
        "private Context Brain parity",
        "live memory retrieval",
        "live semantic search",
        "provider-backed intelligence",
        "MCP production ready",
        "GPT Actions production ready",
    )
    source_lower = IMPLEMENTATION_SOURCE.lower()
    for phrase in forbidden_affirmative:
        assert phrase.lower() not in source_lower
    assert "not_production_ingestion_runtime" in B27_NON_CLAIMS
    assert "not_mcp_or_gpt_actions_production_ready" in B27_NON_CLAIMS
