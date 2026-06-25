"""M2 persistence backend selector.

The selector is the only M2 wiring seam: empty environment stays deterministic
and in-memory; an explicit database URL selects the Postgres backend surface.
"""
from __future__ import annotations

import os

from memory_lab.persistence.contracts import PersistenceBackend
from memory_lab.persistence.memory_backend import InMemoryPersistenceBackend


def build_persistence_backend(database_url: str | None = None) -> PersistenceBackend:
    """Return the persistence backend selected by explicit DB configuration.

    database_url=None means read DATABASE_URL from the environment. Empty
    strings and missing environment values select the deterministic in-memory
    backend and must not import or open any SQL driver.
    """
    resolved = os.environ.get("DATABASE_URL", "") if database_url is None else database_url
    if not str(resolved or "").strip():
        return InMemoryPersistenceBackend()

    from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend

    return PostgresPersistenceBackend(str(resolved).strip())
