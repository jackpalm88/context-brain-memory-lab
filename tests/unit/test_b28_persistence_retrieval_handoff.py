from dataclasses import fields

from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult
from memory_lab.retrieval.persistence_handoff import (
    B28_NON_CLAIMS,
    PersistenceRetrievalCandidateRequest,
    PersistenceRetrievalCapabilityMetadata,
    PublicSafePersistenceRetrievalHandoff,
    build_retrieval_candidates_from_records,
)


def _record(content_id="b", workspace_id="ws-a", text="alpha beta gamma", **metadata):
    return ContentPersistenceRecord(
        content_id=content_id,
        workspace_id=workspace_id,
        text=text,
        title=f"Title {content_id}",
        metadata={
            "domain": "engineering",
            "tags": ("alpha", "beta"),
            "scoring_composite": 0.73,
            "tier_recommendation": "warm",
            "secret": "not-copied",
            **metadata,
        },
    )


def test_converts_supplied_content_persistence_records_to_b23_candidates():
    result = build_retrieval_candidates_from_records((_record("b"), _record("a", text="context memory handoff")), workspace_id="ws-a")

    assert result.ok is True
    assert result.status == "completed"
    assert [candidate.item_id for candidate in result.candidates] == ["a", "b"]
    first = result.candidates[0]
    assert first.text == "context memory handoff"
    assert first.snippet == "context memory handoff"
    assert first.domain == "engineering"
    assert first.tags == ("alpha", "beta")
    assert first.ingestion_score == 0.73
    assert first.tier == "warm"
    assert first.source_metadata["domain"] == "engineering"
    assert "secret" not in first.source_metadata
    assert result.non_claims == B28_NON_CLAIMS


def test_converts_mapping_records_and_bounds_snippets():
    result = build_retrieval_candidates_from_records(
        (
            {
                "content_id": "map-1",
                "workspace_id": "ws-a",
                "content": "0123456789abcdef",
                "title": "Mapped",
                "metadata": {"domain": "docs", "tags": ["x"], "scoring_composite": "0.9"},
            },
        ),
        workspace_id="ws-a",
    )

    assert result.ok is True
    assert result.candidates[0].item_id == "map-1"
    assert result.candidates[0].text == "0123456789abcdef"
    assert result.candidates[0].snippet == "0123456789abcdef"
    assert result.candidates[0].ingestion_score == 0.9

    bounded = PublicSafePersistenceRetrievalHandoff().build_candidates(
        PersistenceRetrievalCandidateRequest(workspace_id="ws-a", records=(_record("short", text="abcdef"),), snippet_chars=3)
    )
    assert bounded.candidates[0].snippet == "abc"


def test_direct_records_do_not_require_backend_even_when_backend_absent():
    result = build_retrieval_candidates_from_records((_record("direct"),), workspace_id="ws-a")
    assert result.ok is True
    assert result.errors == ()


def test_backend_mode_without_backend_returns_structured_backend_required_error():
    result = build_retrieval_candidates_from_records((), workspace_id="ws-a", use_backend=True)
    assert result.ok is False
    assert result.status == "backend_required"
    assert result.errors[0].code == "backend_required"
    assert result.errors[0].field == "backend"


class FailingBackend:
    def list_content_records(self, workspace_id):
        return PersistenceResult.failure("list_content_records", "boom", "backend failed", "backend")


def test_backend_failure_returns_structured_backend_result_failed_error():
    result = build_retrieval_candidates_from_records((), workspace_id="ws-a", backend=FailingBackend(), use_backend=True)
    assert result.ok is False
    assert result.status == "backend_result_failed"
    assert result.errors[0].code == "backend_result_failed"
    assert result.errors[0].message == "backend failed"


def test_false_capability_metadata_and_limitations_are_present():
    result = build_retrieval_candidates_from_records((_record("meta"),), workspace_id="ws-a")
    metadata = result.capability_metadata
    false_fields = (
        "live_backend_used",
        "requires_db",
        "requires_provider",
        "requires_private_context_brain",
        "uses_embeddings",
        "uses_vector_db",
        "mutates_external_state",
    )
    for field_name in false_fields:
        assert getattr(metadata, field_name) is False
    assert "persistence_to_retrieval_handoff_contract_only" in metadata.limitations
    for required in (
        "not_live_memory_retrieval",
        "not_semantic_search",
        "not_db_backed_retrieval",
        "not_db_backed_production_persistence",
        "not_provider_backed_reasoning",
        "not_embedding_or_vector_retrieval",
        "not_private_context_brain_parity",
        "not_full_context_brain_parity",
        "not_api_or_mcp_runtime",
        "not_production_ready",
    ):
        assert required in metadata.non_claims
    assert "capability" in {field.name for field in fields(PersistenceRetrievalCapabilityMetadata)}
