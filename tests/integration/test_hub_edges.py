"""Integration tests — hub edge backend. Skips without CB_TEST_DATABASE_URL."""
import os
import uuid
import pytest

TEST_DSN = os.environ.get("CB_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
_TEST_PREFIX = "pytest_edge_"
pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.public_safe]


def _require_dsn():
    if not TEST_DSN:
        pytest.skip("CB_TEST_DATABASE_URL / DATABASE_URL not set")


def test_edge_key_dedup():
    _require_dsn()
    from memory_lab.graph.hub_edge_store import _compute_edge_key
    src_id = str(uuid.uuid4())
    tgt_id = str(uuid.uuid4())
    assert _compute_edge_key(src_id, tgt_id, "related") == _compute_edge_key(tgt_id, src_id, "related")
