from memory_lab.ingestion.pipeline_contract import IngestionPipelineRequest, run_ingestion_pipeline
from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend


def _request(**overrides):
    data = {
        "workspace_id": "workspace-b27-persist",
        "content_id": "persist-content",
        "text": "A caller supplied public-safe ingestion note with governance evidence, quality tests, and deterministic workflow boundaries.",
        "title": "Persistence boundary",
        "persist": False,
    }
    data.update(overrides)
    return IngestionPipelineRequest(**data)


def test_persist_false_requires_no_backend_and_does_not_mutate_persistence():
    result = run_ingestion_pipeline(_request(persist=False))
    assert result.ok
    assert result.persistence["attempted"] is False
    assert result.persistence["backend_required"] is False
    assert result.persistence["result"] is None


def test_persist_true_without_backend_returns_persistence_backend_required():
    result = run_ingestion_pipeline(_request(persist=True), backend=None)
    assert not result.ok
    assert result.status == "persistence_backend_required"
    assert result.errors[0].code == "persistence_backend_required"
    assert result.persistence["attempted"] is False


def test_persist_true_with_in_memory_backend_writes_only_through_b26_backend():
    backend = InMemoryPersistenceBackend()
    request = _request(persist=True)
    result = run_ingestion_pipeline(request, backend=backend)
    assert result.ok
    assert result.persistence["attempted"] is True
    assert result.persistence["result"].ok is True
    fetched = backend.get_content_record(request.workspace_id, request.content_id)
    assert fetched.ok is True
    assert fetched.value.workspace_id == request.workspace_id
    assert fetched.value.content_id == request.content_id
    assert fetched.value.metadata["b27_mode"].startswith("b27_public_safe")


def test_repeated_writes_are_idempotent_through_b26_backend():
    backend = InMemoryPersistenceBackend()
    request = _request(persist=True)
    first = run_ingestion_pipeline(request, backend=backend)
    second = run_ingestion_pipeline(request, backend=backend)
    assert first.ok and second.ok
    listed = backend.list_content_records(request.workspace_id)
    assert listed.ok
    assert len(listed.value) == 1
    assert listed.value[0].content_id == request.content_id


def test_no_db_fallback_when_backend_missing():
    result = run_ingestion_pipeline(_request(persist=True))
    assert not result.ok
    assert result.persistence["backend_required"] is True
    assert result.persistence["result"] is None
