"""
pytest configuration — marker registration for the public Memory Lab test suite.
"""
import pytest


@pytest.fixture(autouse=True)
def _provider_optional_forces_fallback_path(request, monkeypatch):
    """provider_optional means "exercises the fallback path" — a real provider
    key ambient in the developer's shell would silently reroute these tests
    through live LLM scoring: nondeterministic results (short fixture texts
    get governance-discarded) and per-run API spend. Tests that need a key
    set a fake one themselves inside the test body, which happens after this
    setup and therefore still works."""
    if request.node.get_closest_marker("provider_optional"):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: pure-Python, no DB, no provider, no network")
    config.addinivalue_line("markers", "integration: requires live PostgreSQL (skip without CB_TEST_DATABASE_URL)")
    config.addinivalue_line("markers", "smoke: package asset / import smoke")
    config.addinivalue_line("markers", "requires_db: test skips without CB_TEST_DATABASE_URL")
    config.addinivalue_line("markers", "provider_optional: passes without API key (exercises fallback path)")
    config.addinivalue_line("markers", "skipped_without_env: skips if required env var absent")
    config.addinivalue_line("markers", "public_safe: no private data, safe to publish")
