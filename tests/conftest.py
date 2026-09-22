"""
pytest configuration — marker registration for the public Memory Lab test suite.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_mcp_caller_auth_state():
    """memory_lab.mcp.client holds process-global state for the MCP
    workspace-scoping fix (is_authenticated_http_mode_active(), the caller-context
    contextvar) that MCPBearerAuthMiddleware and build_asgi_app() mutate as a side
    effect of construction/import -- including transitively, e.g. any test that
    imports or reloads memory_lab.mcp.http_server. Without a reset, one test's
    side effect can make an unrelated test's from_env() call unexpectedly fail
    closed (or vice versa). Reset before AND after every test, project-wide, so
    no test's import/construction order can leak into another's."""
    from memory_lab.mcp.client import (
        reset_caller_auth_context,
        set_authenticated_http_mode_active,
        set_caller_auth_context,
    )

    def _reset():
        set_authenticated_http_mode_active(False)
        token = set_caller_auth_context(None)
        reset_caller_auth_context(token)

    _reset()
    yield
    _reset()


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
