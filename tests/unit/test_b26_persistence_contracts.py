from dataclasses import fields, is_dataclass

from memory_lab.persistence.contracts import ContentPersistenceBackend, GovernanceStatePersistenceBackend, PersistenceBackend
from memory_lab.persistence.results import (
    B26_LIMITATIONS,
    B26_MODE,
    B26_NON_CLAIMS,
    ContentPersistenceRecord,
    PersistenceError,
    PersistenceOperationMetadata,
    PersistenceResult,
)


def test_b26_protocol_names_exist():
    assert ContentPersistenceBackend.__name__ == "ContentPersistenceBackend"
    assert GovernanceStatePersistenceBackend.__name__ == "GovernanceStatePersistenceBackend"
    assert PersistenceBackend.__name__ == "PersistenceBackend"


def test_result_error_metadata_dataclasses_expose_required_fields():
    assert is_dataclass(PersistenceResult)
    assert is_dataclass(PersistenceError)
    assert is_dataclass(PersistenceOperationMetadata)
    assert is_dataclass(ContentPersistenceRecord)
    metadata_fields = {field.name for field in fields(PersistenceOperationMetadata)}
    assert {
        "mode",
        "live_backend_used",
        "requires_db",
        "requires_provider",
        "requires_private_context_brain",
        "uses_embeddings",
        "uses_vector_db",
        "mutates_external_state",
        "limitations",
        "non_claims",
    } <= metadata_fields


def test_metadata_is_public_safe_and_deterministic():
    meta = PersistenceOperationMetadata()
    assert meta.mode == B26_MODE
    assert meta.live_backend_used is False
    assert meta.requires_db is False
    assert meta.requires_provider is False
    assert meta.requires_private_context_brain is False
    assert meta.uses_embeddings is False
    assert meta.uses_vector_db is False
    assert meta.mutates_external_state is False
    assert "no_database_access" in meta.limitations
    assert "no_migrations" in meta.limitations
    assert "not_database_backed_runtime" in meta.non_claims
    assert B26_LIMITATIONS == meta.limitations
    assert B26_NON_CLAIMS == meta.non_claims


def test_success_and_failure_results_are_structured():
    ok = PersistenceResult.success("op", {"x": 1})
    err = PersistenceResult.failure("op", "bad", "bad input", "field")
    assert ok.ok is True
    assert ok.value == {"x": 1}
    assert ok.error is None
    assert err.ok is False
    assert err.error.code == "bad"
    assert err.error.field == "field"
    assert err.metadata.requires_db is False


def test_no_affirmative_readiness_claims_in_metadata_text():
    text = " ".join(B26_LIMITATIONS + B26_NON_CLAIMS).lower()
    forbidden = (
        "production persistence ready",
        "production db-backed persistence",
        "db-backed production persistence",
        "full context brain ready",
        "live semantic search",
        "provider-backed reasoning",
    )
    for phrase in forbidden:
        assert phrase not in text
