from memory_lab.governance.tier_routing_plan import TierRoutingPlan
from memory_lab.ingestion.pipeline_contract import (
    B27_LIMITATIONS,
    B27_NON_CLAIMS,
    B27_PIPELINE_MODE,
    IngestionPipelineRequest,
    IngestionPipelineResult,
    PublicSafeIngestionPipeline,
    make_public_safe_ingestion_pipeline,
    run_ingestion_pipeline,
)


def _request(**overrides):
    data = {
        "workspace_id": "workspace-b27",
        "content_id": "content-b27",
        "title": "Governance quality planning note",
        "text": "# Governance Quality Plan\n\nThis public-safe governance planning note documents tests, evidence, workflow boundaries, and implementation review. It is caller supplied text only.",
        "hub_candidates": (
            {"title": "Governance Quality", "aliases": ("governance quality",), "related_terms": ("evidence", "review")},
        ),
        "metadata": {"source": "unit-test"},
    }
    data.update(overrides)
    return IngestionPipelineRequest(**data)


def test_public_surface_and_constants_exist():
    pipeline = make_public_safe_ingestion_pipeline()
    assert isinstance(pipeline, PublicSafeIngestionPipeline)
    assert B27_PIPELINE_MODE == "b27_public_safe_ingestion_pipeline_contract_v1"
    assert "requires_explicit_workspace_id" in B27_LIMITATIONS
    assert "not_production_ingestion_runtime" in B27_NON_CLAIMS


def test_request_requires_workspace_id_and_invalid_workspace_returns_structured_error():
    result = run_ingestion_pipeline(_request(workspace_id=""))
    assert not result.ok
    assert result.status == "invalid_request"
    assert result.errors[0].code == "invalid_workspace_id"
    assert result.errors[0].field == "workspace_id"


def test_missing_content_id_returns_structured_error():
    result = run_ingestion_pipeline(_request(content_id=""))
    assert not result.ok
    assert any(error.code == "missing_content_id" for error in result.errors)


def test_missing_or_blank_text_returns_structured_error():
    result = run_ingestion_pipeline(_request(text="  \n"))
    assert not result.ok
    assert any(error.code == "missing_text" for error in result.errors)


def test_deterministic_result_for_same_input():
    first = run_ingestion_pipeline(_request())
    second = run_ingestion_pipeline(_request())
    assert first.ok and second.ok
    assert first.request_id == second.request_id
    assert first.domain.domain == second.domain.domain
    assert tuple(first.hubs.hub_candidates) == tuple(second.hubs.hub_candidates)
    assert tuple(chunk.chunk_id for chunk in first.chunks) == tuple(chunk.chunk_id for chunk in second.chunks)
    assert first.scoring.score.composite == second.scoring.score.composite


def test_pipeline_outputs_contract_components_and_plan_only_tier():
    result: IngestionPipelineResult = run_ingestion_pipeline(_request())
    assert result.ok
    assert result.extraction.extracted_text
    assert result.domain.domain in {"governance", "planning", "quality", "ambiguous", "unknown"}
    assert result.hubs is not None
    assert result.tags is not None
    assert result.chunks
    assert result.chunk_scores
    assert result.scoring.score.composite >= 0.0
    assert result.circuit.state == "closed"
    assert isinstance(result.tier_plan, TierRoutingPlan)
    assert result.tier_plan.plan_only is True
    assert result.mode == B27_PIPELINE_MODE
    assert "not_private_context_brain_parity" in result.non_claims
    assert "tier_routing_plan_only" in result.limitations
