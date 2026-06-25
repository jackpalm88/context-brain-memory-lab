"""B26 public-safe persistence contract package."""
from memory_lab.persistence.contracts import ContentPersistenceBackend, GovernanceStatePersistenceBackend, PersistenceBackend
from memory_lab.persistence.factory import build_persistence_backend
from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend
from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend
from memory_lab.persistence.results import (
    B26_LIMITATIONS,
    B26_MODE,
    B26_NON_CLAIMS,
    ContentPersistenceRecord,
    PersistenceError,
    PersistenceOperationMetadata,
    PersistenceResult,
)

__all__ = (
    "B26_LIMITATIONS",
    "B26_MODE",
    "B26_NON_CLAIMS",
    "build_persistence_backend",
    "ContentPersistenceBackend",
    "ContentPersistenceRecord",
    "GovernanceStatePersistenceBackend",
    "InMemoryPersistenceBackend",
    "PersistenceBackend",
    "PostgresPersistenceBackend",
    "PersistenceError",
    "PersistenceOperationMetadata",
    "PersistenceResult",
)
