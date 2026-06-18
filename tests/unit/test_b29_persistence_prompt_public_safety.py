from dataclasses import fields
from pathlib import Path

from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.reasoning import persistence_prompt_handoff as module
from memory_lab.reasoning.persistence_prompt_handoff import (
    B29_NON_CLAIMS,
    PersistencePromptCapabilityMetadata,
    build_prompt_package_from_persisted_records,
)


MODULE_PATH = Path(module.__file__)
SOURCE = MODULE_PATH.read_text(encoding="utf-8")


def _record():
    return ContentPersistenceRecord(
        content_id="safe",
        workspace_id="ws-a",
        text="safe prompt evidence",
        title="Safe",
        metadata={"domain": "docs", "tags": ("safe",)},
    )


def test_runtime_forbidden_patterns_are_absent_from_b29_module():
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
        "MCP server",
        "FastAPI",
        "APIRouter",
        "Depends",
        "migrations",
        "alembic",
        "put_content_record",
        "execute_llm_request",
        "complete_",
    )
    for pattern in forbidden:
        assert pattern not in SOURCE


def test_success_and_failure_surface_explicit_non_claims_and_false_metadata():
    success = build_prompt_package_from_persisted_records((_record(),), workspace_id="ws-a", query="safe")
    failure = build_prompt_package_from_persisted_records((), workspace_id="ws-a", query="safe")

    assert success.ok is True
    assert failure.ok is False
    for result in (success, failure):
        assert result.non_claims == B29_NON_CLAIMS
        assert "not_llm_execution" in result.non_claims
        assert "not_provider_backed_reasoning" in result.non_claims
        assert "not_private_context_brain_parity" in result.non_claims
        metadata = result.capability_metadata
        for field_name in (
            "live_backend_used",
            "requires_db",
            "requires_provider",
            "requires_private_context_brain",
            "uses_embeddings",
            "uses_vector_db",
            "mutates_external_state",
            "executes_llm",
            "production_runtime",
        ):
            assert getattr(metadata, field_name) is False


def test_capability_metadata_exposes_required_false_capability_fields():
    field_names = {field.name for field in fields(PersistencePromptCapabilityMetadata)}

    assert {
        "live_backend_used",
        "requires_db",
        "requires_provider",
        "requires_private_context_brain",
        "uses_embeddings",
        "uses_vector_db",
        "mutates_external_state",
        "executes_llm",
        "production_runtime",
    }.issubset(field_names)


def test_claim_scan_has_no_forbidden_affirmative_runtime_claims_outside_non_claims():
    forbidden_affirmative = (
        "production ready",
        "production retrieval",
        "live memory retrieval",
        "live semantic search",
        "searches context brain",
        "private context brain parity",
        "full context brain ready",
        "db-backed retrieval",
        "db-backed production persistence",
        "provider-backed reasoning",
        "generated embeddings",
        "vector search",
        "mcp production ready",
        "gpt actions production ready",
        "executed llm answer generation",
    )
    lowered = SOURCE.lower()
    for phrase in forbidden_affirmative:
        assert phrase not in lowered


def test_no_api_mcp_or_runtime_wiring_is_exposed():
    lowered = SOURCE.lower()
    assert "route" not in lowered
    assert "server" not in lowered
    assert "tool" not in lowered
    assert "http" not in lowered
    assert "os.environ" not in SOURCE
