from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.reasoning.persistence_prompt_handoff import (
    B29_NON_CLAIMS,
    PersistencePromptPackageRequest,
    PublicSafePersistencePromptPackageHandoff,
    build_prompt_package_from_persisted_records,
)


def _record(content_id="a", workspace_id="ws-a", text="alpha memory prompt package evidence", **metadata):
    return ContentPersistenceRecord(
        content_id=content_id,
        workspace_id=workspace_id,
        text=text,
        title=f"Title {content_id}",
        metadata={
            "domain": "engineering",
            "tags": ("alpha", "prompt"),
            "scoring_composite": 0.84,
            "tier_recommendation": "warm",
            "secret": "must-not-copy",
            **metadata,
        },
    )


def test_builds_b23_prompt_package_from_content_persistence_records():
    result = build_prompt_package_from_persisted_records(
        (_record("b", text="unrelated note"), _record("a", text="alpha memory prompt package evidence")),
        workspace_id="ws-a",
        query="alpha prompt",
        purpose="answer",
    )

    assert result.ok is True
    assert result.status == "completed_with_prompt_package"
    assert result.prompt_package is not None
    assert result.context_handoff is not None
    assert result.context_handoff.context_package is not None
    assert result.prompt_package.scope == "public_safe_provider_neutral_prompt_package_only"
    assert result.prompt_package.evidence_ids == tuple(ref.evidence_id for ref in result.context_handoff.context_package.evidence)
    assert "alpha memory prompt package evidence" in result.prompt_package.prompt
    assert "secret" not in result.prompt_package.prompt
    assert result.non_claims == B29_NON_CLAIMS


def test_prompt_handoff_is_deterministic_for_identical_inputs():
    records = (_record("b", text="beta prompt evidence"), _record("a", text="alpha prompt evidence"))

    first = build_prompt_package_from_persisted_records(records, workspace_id="ws-a", query="prompt", purpose="cite")
    second = build_prompt_package_from_persisted_records(records, workspace_id="ws-a", query="prompt", purpose="cite")

    assert first.ok is True
    assert second.ok is True
    assert first.prompt_package == second.prompt_package
    assert first.context_handoff.candidates == second.context_handoff.candidates


def test_accepts_mapping_records_through_b28_path_and_keeps_public_safe_metadata():
    result = build_prompt_package_from_persisted_records(
        (
            {
                "content_id": "map-1",
                "workspace_id": "ws-a",
                "content": "mapped prompt evidence",
                "title": "Mapped",
                "metadata": {
                    "domain": "docs",
                    "tags": ["mapped"],
                    "scoring_composite": "0.91",
                    "tier_recommendation": "hot",
                    "private_token": "not-copied",
                },
            },
        ),
        workspace_id="ws-a",
        query="mapped prompt",
    )

    assert result.ok is True
    candidate = result.context_handoff.candidates[0]
    assert candidate.item_id == "map-1"
    assert candidate.ingestion_score == 0.91
    assert candidate.source_metadata["domain"] == "docs"
    assert "private_token" not in candidate.source_metadata
    assert "mapped prompt evidence" in result.prompt_package.prompt
    assert "private_token" not in result.prompt_package.prompt


def test_no_usable_records_returns_structured_error_with_non_claims():
    result = build_prompt_package_from_persisted_records((), workspace_id="ws-a", query="empty")

    assert result.ok is False
    assert result.status == "no_usable_records"
    assert result.errors[0].code == "no_usable_records"
    assert result.errors[0].field == "records"
    assert "not_llm_execution" in result.errors[0].non_claims
    assert result.capability_metadata.executes_llm is False


def test_context_package_failed_is_structured_when_b28_returns_no_package(monkeypatch):
    from memory_lab.reasoning import persistence_prompt_handoff as module
    from memory_lab.retrieval.persistence_handoff import PersistenceRetrievalHandoffResult

    def fake_context_result(request):
        return PersistenceRetrievalHandoffResult(ok=True, status="completed", workspace_id=request.workspace_id)

    monkeypatch.setattr(module, "_build_context_result", fake_context_result)

    result = build_prompt_package_from_persisted_records((_record(),), workspace_id="ws-a", query="alpha")

    assert result.ok is False
    assert result.status == "context_package_failed"
    assert result.errors[0].code == "context_package_failed"


def test_prompt_package_failed_is_structured_when_b23_builder_fails(monkeypatch):
    from memory_lab.reasoning import persistence_prompt_handoff as module

    def fail_prompt_builder(request):
        raise ValueError("prompt builder failed")

    monkeypatch.setattr(module, "build_prompt_package", fail_prompt_builder)

    result = build_prompt_package_from_persisted_records((_record(),), workspace_id="ws-a", query="alpha")

    assert result.ok is False
    assert result.status == "prompt_package_failed"
    assert result.errors[0].code == "prompt_package_failed"
    assert result.errors[0].field == "prompt_package"
    assert "prompt builder failed" in result.errors[0].message


def test_class_interface_builds_prompt_package():
    request = PersistencePromptPackageRequest(workspace_id="ws-a", records=(_record(),), query="alpha")

    result = PublicSafePersistencePromptPackageHandoff().build_prompt_package(request)

    assert result.ok is True
    assert result.prompt_package is not None
    assert PublicSafePersistencePromptPackageHandoff.name == "PublicSafePersistencePromptPackageHandoff"
