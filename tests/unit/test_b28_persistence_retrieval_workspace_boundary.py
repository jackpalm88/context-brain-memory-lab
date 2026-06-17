from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend
from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.retrieval.persistence_handoff import PersistenceRetrievalCandidateRequest, PublicSafePersistenceRetrievalHandoff, build_retrieval_candidates_from_records


def _record(content_id, workspace_id, text="workspace scoped text"):
    return ContentPersistenceRecord(content_id=content_id, workspace_id=workspace_id, text=text, metadata={"domain": "workspace"})


def test_workspace_id_required_and_validated_with_b25():
    result = build_retrieval_candidates_from_records((_record("a", "ws-a"),), workspace_id="")

    assert result.ok is False
    assert result.status == "invalid_workspace"
    assert result.errors[0].code == "invalid_workspace_id"
    assert "workspace_id is required" in result.errors[0].message


def test_cross_workspace_records_are_rejected():
    result = build_retrieval_candidates_from_records((_record("a", "ws-a"), _record("b", "ws-b")), workspace_id="ws-a")

    assert result.ok is False
    assert result.status == "workspace_boundary_violation"
    assert result.errors[0].code == "workspace_boundary_violation"


def test_same_content_id_across_workspaces_does_not_collide_when_read_from_supplied_backend():
    backend = InMemoryPersistenceBackend()
    assert backend.put_content_record(_record("same", "ws-a", "alpha workspace")).ok
    assert backend.put_content_record(_record("same", "ws-b", "beta workspace")).ok

    handoff = PublicSafePersistenceRetrievalHandoff()
    result_a = handoff.build_candidates(PersistenceRetrievalCandidateRequest(workspace_id="ws-a", backend=backend, use_backend=True))
    result_b = handoff.build_candidates(PersistenceRetrievalCandidateRequest(workspace_id="ws-b", backend=backend, use_backend=True))

    assert result_a.ok is True
    assert result_b.ok is True
    assert result_a.candidates[0].item_id == "same"
    assert result_b.candidates[0].item_id == "same"
    assert result_a.candidates[0].text == "alpha workspace"
    assert result_b.candidates[0].text == "beta workspace"


def test_supplied_backend_list_path_preserves_b25_b26_boundaries():
    backend = InMemoryPersistenceBackend()
    backend.put_content_record(_record("a", "ws-a"))
    backend.put_content_record(_record("b", "ws-b"))

    result = build_retrieval_candidates_from_records((), workspace_id="ws-a", backend=backend, use_backend=True)

    assert result.ok is True
    assert [candidate.item_id for candidate in result.candidates] == ["a"]
    assert result.handoff_candidates[0].workspace_id == "ws-a"
