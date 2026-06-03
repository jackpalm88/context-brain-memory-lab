"""
pytest configuration — marker registration for the public Memory Lab test suite.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: pure-Python, no DB, no provider, no network")
    config.addinivalue_line("markers", "integration: requires live PostgreSQL (skip without CB_TEST_DATABASE_URL)")
    config.addinivalue_line("markers", "smoke: package asset / import smoke")
    config.addinivalue_line("markers", "requires_db: test skips without CB_TEST_DATABASE_URL")
    config.addinivalue_line("markers", "provider_optional: passes without API key (exercises fallback path)")
    config.addinivalue_line("markers", "skipped_without_env: skips if required env var absent")
    config.addinivalue_line("markers", "public_safe: no private data, safe to publish")
