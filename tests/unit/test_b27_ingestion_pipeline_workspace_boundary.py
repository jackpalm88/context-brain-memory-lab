from memory_lab.ingestion.pipeline_contract import IngestionPipelineRequest, run_ingestion_pipeline
from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend


def _request(workspace_id, content_id="shared-content", **overrides):
    data = {
        "workspace_id": workspace_id,
        "content_id": content_id,
        "text": "Governance review evidence and public-safe workflow boundaries are supplied by the caller for deterministic hub and tag signals.",
        "title": "Workspace boundary",
        "hub_candidates": ({"title": "Governance Review", "aliases": ("governance review",), "related_terms": ("evidence",)},),
        "metadata": {"kind": "unit"},
    }
    data.update(overrides)
    return IngestionPipelineRequest(**data)


def test_workspace_id_required():
    result = run_ingestion_pipeline(_request(""))
    assert not result.ok
    assert any(error.field == "workspace_id" for error in result.errors)


def test_same_content_id_across_different_workspaces_does_not_collide():
    backend = InMemoryPersistenceBackend()
    first = _request("workspace-one", persist=True)
    second = _request("workspace-two", persist=True)
    assert run_ingestion_pipeline(first, backend=backend).ok
    assert run_ingestion_pipeline(second, backend=backend).ok
    first_record = backend.get_content_record("workspace-one", "shared-content")
    second_record = backend.get_content_record("workspace-two", "shared-content")
    assert first_record.ok and second_record.ok
    assert first_record.value.workspace_id == "workspace-one"
    assert second_record.value.workspace_id == "workspace-two"


def test_workspace_boundary_preserved_through_b26_backend():
    backend = InMemoryPersistenceBackend()
    request = _request("workspace-boundary", persist=True)
    result = run_ingestion_pipeline(request, backend=backend)
    assert result.ok
    assert result.workspace_id == "workspace-boundary"
    fetched = backend.get_content_record("workspace-boundary", "shared-content")
    assert fetched.ok
    assert fetched.value.workspace_id == result.workspace_id


def test_supplied_hub_and_tag_candidates_used_without_live_graph_lookup():
    request = _request(
        "workspace-boundary",
        hub_candidates=({"title": "Governance Review", "aliases": ("governance review",), "related_terms": ("workflow",)},),
        tag_candidates=("governance", "review"),
    )
    result = run_ingestion_pipeline(request)
    assert result.ok
    assert "governance_review" in tuple(result.hubs.hub_candidates)
    assert tuple(result.tags.tags)
    assert result.extraction.fields["title_candidate"]
