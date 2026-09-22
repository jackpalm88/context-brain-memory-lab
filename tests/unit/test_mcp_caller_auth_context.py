"""MCP workspace-scoping fix (Phase B/C) — caller-context propagation tests.

Fix for the confused-deputy gap: memory_lab/mcp/http_auth.py populates a
request-scoped MCPCallerAuthContext (the caller's OWN bearer token + their
middleware-resolved default workspace) for the duration of one streamable-http
request; memory_lab/mcp/client.py's MemoryLabApiClient.from_env() prefers that
context over the static MEMORY_LAB_API_TOKEN service credential. In api_key
mode, a missing context fails closed rather than falling back to the shared
credential. Fallback to the static token remains only for stdio / auth_mode=none.

See docs/MCP_WORKSPACE_SCOPING_FIX_PLAN.md and OpenCB decisions
2b1c676b-4b2c-48ca-b253-d7b6428e1d75 / 4294c3da-1fb3-4816-b3f6-a31c53e78295 /
0ac855b1-634e-49b8-bdcb-7c74f474179a.

Module-level global state (`_authenticated_http_mode_active`, the caller-context
contextvar) is reset before and after every test in this file so nothing leaks
into other test modules sharing the same pytest process.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from memory_lab.mcp.client import (
    MCPCallerAuthContext,
    MemoryLabApiClient,
    MemoryLabApiError,
    get_caller_auth_context,
    is_authenticated_http_mode_active,
    reset_caller_auth_context,
    set_authenticated_http_mode_active,
    set_caller_auth_context,
)

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


@pytest.fixture(autouse=True)
def _reset_mcp_auth_state():
    set_authenticated_http_mode_active(False)
    token = set_caller_auth_context(None)
    reset_caller_auth_context(token)
    yield
    set_authenticated_http_mode_active(False)
    token = set_caller_auth_context(None)
    reset_caller_auth_context(token)


def _env_no_secrets(**overrides):
    base = {
        "MEMORY_LAB_API_HOST": "127.0.0.1",
        "MEMORY_LAB_API_PORT": "8000",
        "MEMORY_LAB_API_SCHEME": "http",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# from_env() precedence: caller context > authenticated-http fail-closed >
# static token fallback.
# ---------------------------------------------------------------------------
def test_from_env_uses_caller_context_when_present():
    set_authenticated_http_mode_active(True)
    ctx = MCPCallerAuthContext(bearer_token="caller-own-token", resolved_default_workspace_id="ws-caller")
    token = set_caller_auth_context(ctx)
    try:
        with patch.dict(os.environ, _env_no_secrets(), clear=True):
            client = MemoryLabApiClient.from_env()
        assert client.api_token == "caller-own-token"
        assert client.default_workspace_id == "ws-caller"
        assert client.fail_closed_reason is None
    finally:
        reset_caller_auth_context(token)


def test_from_env_fails_closed_when_http_mode_active_and_context_missing():
    set_authenticated_http_mode_active(True)
    # No caller context set (autouse fixture already ensures it's clear).
    with patch.dict(os.environ, _env_no_secrets(MEMORY_LAB_API_TOKEN="static-should-never-be-used"), clear=True):
        client = MemoryLabApiClient.from_env()
    assert client.fail_closed_reason is not None
    assert client.api_token is None  # never populated with the static token
    with pytest.raises(MemoryLabApiError, match="authenticated_http_missing_caller_context"):
        client.health()


def test_from_env_falls_back_to_static_token_when_http_mode_inactive():
    # http mode never active == stdio server / auth_mode=none: unchanged behavior.
    set_authenticated_http_mode_active(False)
    with patch.dict(
        os.environ,
        _env_no_secrets(
            MEMORY_LAB_API_TOKEN="static-service-token",
            MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID="ws-static-default",
        ),
        clear=True,
    ):
        client = MemoryLabApiClient.from_env()
    assert client.api_token == "static-service-token"
    assert client.default_workspace_id == "ws-static-default"
    assert client.fail_closed_reason is None


def test_explicit_workspace_id_argument_still_overrides_caller_default():
    # Preserves multi-workspace callers: an explicit workspace_id argument still
    # wins over the caller's own resolved default -- REST is what actually
    # authorizes it, this layer just forwards the caller's own token either way.
    set_authenticated_http_mode_active(True)
    ctx = MCPCallerAuthContext(bearer_token="caller-own-token", resolved_default_workspace_id="ws-caller-default")
    token = set_caller_auth_context(ctx)
    try:
        with patch.dict(os.environ, _env_no_secrets(), clear=True):
            client = MemoryLabApiClient.from_env()
        headers = client._headers(workspace_id="ws-explicit-other")
        assert headers["X-Workspace-ID"] == "ws-explicit-other"
        assert headers["Authorization"] == "Bearer caller-own-token"
    finally:
        reset_caller_auth_context(token)


# ---------------------------------------------------------------------------
# _request() fail-closed: never makes a network call.
# ---------------------------------------------------------------------------
def test_request_raises_before_any_network_call_when_fail_closed():
    client = MemoryLabApiClient(base_url="http://127.0.0.1:8000", fail_closed_reason="test_fail_closed")
    with patch("memory_lab.mcp.client.requests.request") as mock_request:
        with pytest.raises(MemoryLabApiError, match="test_fail_closed"):
            client._request("GET", "/health")
        mock_request.assert_not_called()


# ---------------------------------------------------------------------------
# Redaction: a forwarded caller token must never leak in an error body.
# ---------------------------------------------------------------------------
def test_forwarded_caller_token_is_redacted_on_connection_failure():
    ctx = MCPCallerAuthContext(bearer_token="super-secret-caller-token", resolved_default_workspace_id="ws-x")
    token = set_caller_auth_context(ctx)
    try:
        set_authenticated_http_mode_active(True)
        with patch.dict(os.environ, _env_no_secrets(), clear=True):
            client = MemoryLabApiClient(base_url="http://127.0.0.1:1", api_token=ctx.bearer_token, timeout_s=0.2)
        with pytest.raises(MemoryLabApiError) as exc_info:
            client._request("GET", "/health")
        assert "super-secret-caller-token" not in str(exc_info.value)
        assert exc_info.value.body is None or "super-secret-caller-token" not in exc_info.value.body
    finally:
        reset_caller_auth_context(token)


# ---------------------------------------------------------------------------
# Concurrency isolation, exercised against the REAL production functions
# (not a throwaway spike this time).
# ---------------------------------------------------------------------------
def test_contextvar_isolation_under_concurrency():
    set_authenticated_http_mode_active(True)

    async def worker(label: str, ws: str) -> tuple[str | None, str | None]:
        ctx = MCPCallerAuthContext(bearer_token=f"token-{label}", resolved_default_workspace_id=ws)
        token = set_caller_auth_context(ctx)
        try:
            await asyncio.sleep(0.01)
            with patch.dict(os.environ, _env_no_secrets(), clear=True):
                client = MemoryLabApiClient.from_env()
            await asyncio.sleep(0.01)
            # Re-read after another await to widen any task-boundary bug window.
            return client.api_token, get_caller_auth_context().bearer_token
        finally:
            reset_caller_auth_context(token)

    async def run_all():
        return await asyncio.gather(
            worker("A", "ws-A"),
            worker("B", "ws-B"),
            worker("C", "ws-C"),
        )

    results = asyncio.run(run_all())
    assert results[0] == ("token-A", "token-A")
    assert results[1] == ("token-B", "token-B")
    assert results[2] == ("token-C", "token-C")
    # No leakage back into the outer (test) context after the tasks finish.
    assert get_caller_auth_context() is None


def test_contextvar_isolation_missing_context_interleaved_with_populated():
    set_authenticated_http_mode_active(True)

    async def populated(label: str) -> str | None:
        ctx = MCPCallerAuthContext(bearer_token=f"token-{label}", resolved_default_workspace_id="ws")
        token = set_caller_auth_context(ctx)
        try:
            await asyncio.sleep(0.01)
            return get_caller_auth_context().bearer_token
        finally:
            reset_caller_auth_context(token)

    async def missing() -> object:
        await asyncio.sleep(0.01)
        ctx = get_caller_auth_context()
        return ctx

    async def run_all():
        return await asyncio.gather(populated("X"), missing(), populated("Y"))

    results = asyncio.run(run_all())
    assert results[0] == "token-X"
    assert results[1] is None
    assert results[2] == "token-Y"


# ---------------------------------------------------------------------------
# stdio / auth_mode=none path is provably unaffected: is_authenticated_http_mode_active
# defaults False, and the module never sets it without a real api_key-mode middleware.
# ---------------------------------------------------------------------------
def test_authenticated_http_mode_defaults_inactive():
    # Fixture already resets to False; this documents the default explicitly.
    assert is_authenticated_http_mode_active() is False
