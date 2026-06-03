"""Integration tests — graph layer. Skips without CB_TEST_DATABASE_URL."""
import os
import pytest

TEST_DSN = os.environ.get("CB_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.public_safe]


def _require_dsn():
    if not TEST_DSN:
        pytest.skip("CB_TEST_DATABASE_URL / DATABASE_URL not set")


def test_expand_query_returns_list():
    _require_dsn()
    from memory_lab.graph import expand_query
    terms = expand_query("machine learning", dsn=TEST_DSN, limit=5)
    assert isinstance(terms, list)


def test_hybrid_search_returns_list():
    _require_dsn()
    from memory_lab.graph import hybrid_search
    results = hybrid_search("PostgreSQL indexing", dsn=TEST_DSN, limit=5)
    assert isinstance(results, list)
