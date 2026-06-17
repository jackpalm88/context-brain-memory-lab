from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.retrieval.persistence_handoff import PersistenceRetrievalCandidateRequest, PublicSafePersistenceRetrievalHandoff, build_context_package_from_persisted_records


def _record(content_id, text, domain="docs"):
    return ContentPersistenceRecord(
        content_id=content_id,
        workspace_id="ws-a",
        text=text,
        title=f"Title {content_id}",
        metadata={"domain": domain, "tags": ("memory", "handoff"), "scoring_composite": 0.8},
    )


def test_can_rank_via_b23_search_by_purpose_using_supplied_candidates_only():
    result = PublicSafePersistenceRetrievalHandoff().build_context_package(
        PersistenceRetrievalCandidateRequest(
            workspace_id="ws-a",
            records=(
                _record("b", "unrelated note"),
                _record("a", "memory handoff candidate with context package evidence"),
            ),
            query="memory handoff context",
            purpose="answer",
            limit=2,
        )
    )

    assert result.ok is True
    assert result.ranked is not None
    assert result.ranked.scope == "public_safe_supplied_records_deterministic_ranking_only"
    assert result.ranked.results[0].item_id == "a"
    assert result.context_package is not None
    assert result.context_package.scope == "public_safe_stable_evidence_packaging_supplied_records_only"
    assert "memory handoff" in result.context_package.context_text


def test_helper_builds_b23_context_candidate_package_from_handoff_candidates():
    result = build_context_package_from_persisted_records(
        (_record("a", "alpha memory package"),),
        workspace_id="ws-a",
        query="alpha memory",
        purpose="cite",
        max_context_chars=1000,
    )

    assert result.ok is True
    assert result.status == "completed_with_context_package"
    assert result.context_package is not None
    assert result.context_package.evidence[0].item_id == "a"
    assert result.context_package.evidence[0].source_metadata["domain"] == "docs"


def test_context_packaging_remains_supplied_record_only_with_non_claims():
    result = build_context_package_from_persisted_records((_record("a", "safe supplied record"),), workspace_id="ws-a", query="safe")

    assert result.ok is True
    assert result.capability_metadata.live_backend_used is False
    assert result.capability_metadata.requires_db is False
    assert result.capability_metadata.requires_provider is False
    assert result.capability_metadata.requires_private_context_brain is False
    assert result.capability_metadata.uses_embeddings is False
    assert result.capability_metadata.uses_vector_db is False
    assert result.capability_metadata.mutates_external_state is False
    assert "not_live_memory_retrieval" in result.non_claims
    assert "not_private_context_brain_parity" in result.non_claims
