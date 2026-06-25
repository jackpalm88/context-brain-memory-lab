import os

import pytest

from memory_lab.persistence.factory import build_persistence_backend
from memory_lab.persistence.postgres_backend import PostgresPersistenceBackend


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_db,
    pytest.mark.skipped_without_env,
]


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set; real DB persistence is opt-in")
def test_m2_postgres_persistence_integration_is_opt_in():
    backend = build_persistence_backend()
    assert isinstance(backend, PostgresPersistenceBackend)
