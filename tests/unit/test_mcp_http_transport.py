"""MCP-HTTP-1 unit tests — transport layer behavioral contracts.

Scope: tests/unit/test_mcp_http_transport.py
Gate: MCP-HTTP-1

What is tested (transport layer only):
  T1 — ASGI app initializes (streamable_http_app returns a Starlette instance)
  T2 — MCPBearerAuthMiddleware rejects missing token with 401
  T3 — MCPBearerAuthMiddleware rejects malformed token with 401
  T4 — MCPBearerAuthMiddleware in 'none' mode injects default workspace and passes through
  T5 — MCPBearerAuthMiddleware in 'api_key' mode with valid stub token resolves workspace
  T6 — MCPBearerAuthMiddleware injects X-Workspace-ID and strips caller-supplied spoofed header
  T7 — build_asgi_app() hard-fails when AUTH=none on non-loopback host
  T8 — http_config raises on invalid port
  T9 — http_config raises when AUTH=none without MEMORY_LAB_ENV=development
  T10 — _parse_bearer rejects 'Bearer' with no token part

Architecture:
  - No DB. No provider. No network.
  - FakeApp captures injected headers from scope for workspace assertions.
  - asyncio.run() used for async tests (no pytest-asyncio needed).
  - Monkey-patches _resolve_workspace_api_key for T5 stub validation.
"""
from __future__ import annotations

import asyncio
import importlib
import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]


# ─── Helpers ─────────────────────────────────────────────────────────────────


class _FakeApp:
    """Minimal ASGI app that records the headers it received."""

    def __init__(self) -> None:
        self.last_headers: List[tuple] = []
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        self.last_headers = list(scope.get("headers", []))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def _make_scope(
    *,
    path: str = "/mcp",
    auth: Optional[str] = None,
    extra_headers: Optional[list] = None,
) -> Dict[str, Any]:
    headers: List[tuple] = []
    if auth:
        headers.append((b"authorization", auth.encode()))
    if extra_headers:
        headers.extend(extra_headers)
    return {"type": "http", "method": "POST", "path": path, "headers": headers}


async def _noop_receive():
    return {}


def _status_from_sent(sent: list) -> Optional[int]:
    for msg in sent:
        if isinstance(msg, dict) and msg.get("type") == "http.response.start":
            return msg.get("status")
    return None


def _run(coro):
    return asyncio.run(coro)


# ─── T1: ASGI app initializes ────────────────────────────────────────────────


def test_t1_asgi_app_initializes():
    """streamable_http_app() returns a Starlette instance with /mcp route."""
    from starlette.applications import Starlette

    with patch.dict(os.environ, {
        "MEMORY_LAB_ENV": "development",
        "MEMORY_LAB_HTTP_MCP_AUTH": "none",
        "MEMORY_LAB_MCP_HTTP_HOST": "127.0.0.1",
    }, clear=False):
        import memory_lab.mcp.http_server as hs
        importlib.reload(hs)
        raw = hs._server.streamable_http_app()
        assert isinstance(raw, Starlette)
        paths = [getattr(r, "path", None) for r in raw.routes]
        assert "/mcp" in paths, f"Expected /mcp route, got: {paths}"


# ─── T2: Missing token → 401 ─────────────────────────────────────────────────


def test_t2_missing_token_returns_401():
    from memory_lab.mcp.http_auth import MCPBearerAuthMiddleware

    async def _inner():
        fake = _FakeApp()
        mw = MCPBearerAuthMiddleware(
            fake,
            auth_mode="api_key",
            default_workspace_id="00000000-0000-0000-0000-000000000000",
        )
        scope = _make_scope(auth=None)
        sent: list = []

        async def send(m):
            sent.append(m)

        await mw(scope, _noop_receive, send)
        assert _status_from_sent(sent) == 401, f"Expected 401, sent={sent}"
        assert not fake.called

    _run(_inner())


# ─── T3: Malformed token → 401 ────────────────────────────────────────────────


def test_t3_malformed_token_returns_401():
    from memory_lab.mcp.http_auth import MCPBearerAuthMiddleware

    bad_auths = ["Token abc123", "bearer", "Basic dXNlcjpwYXNz"]

    async def _inner():
        for bad_auth in bad_auths:
            fake = _FakeApp()
            mw = MCPBearerAuthMiddleware(
                fake,
                auth_mode="api_key",
                default_workspace_id="00000000-0000-0000-0000-000000000000",
            )
            scope = _make_scope(auth=bad_auth)
            sent: list = []

            async def send(m, _s=sent):
                _s.append(m)

            await mw(scope, _noop_receive, send)
            assert _status_from_sent(sent) == 401, f"Expected 401 for {bad_auth!r}, got sent={sent}"

    _run(_inner())


# ─── T4: auth_mode=none injects workspace and passes through ──────────────────


def test_t4_none_mode_injects_workspace_passthrough():
    from memory_lab.mcp.http_auth import MCPBearerAuthMiddleware

    ws = "aaaaaaaa-0000-0000-0000-000000000001"

    async def _inner():
        fake = _FakeApp()
        mw = MCPBearerAuthMiddleware(fake, auth_mode="none", default_workspace_id=ws)
        scope = _make_scope(auth=None)
        sent: list = []

        async def send(m):
            sent.append(m)

        await mw(scope, _noop_receive, send)
        assert fake.called, "FakeApp was not called"
        injected = dict(fake.last_headers)
        assert injected.get(b"x-workspace-id") == ws.encode(), \
            f"Expected ws={ws!r}, got {injected}"
        assert _status_from_sent(sent) == 200

    _run(_inner())


# ─── T5: Valid stub token resolves workspace ──────────────────────────────────


def test_t5_valid_token_resolves_workspace():
    from memory_lab.mcp.http_auth import MCPBearerAuthMiddleware

    expected_ws = "bbbbbbbb-0000-0000-0000-000000000002"

    async def _inner():
        fake = _FakeApp()
        mw = MCPBearerAuthMiddleware(
            fake,
            auth_mode="api_key",
            default_workspace_id="00000000-0000-0000-0000-000000000000",
        )
        scope = _make_scope(auth="Bearer stub-valid-token-xyz")
        sent: list = []

        async def send(m):
            sent.append(m)

        with patch("memory_lab.mcp.http_auth._resolve_workspace_api_key", return_value=expected_ws):
            await mw(scope, _noop_receive, send)

        assert fake.called
        injected = dict(fake.last_headers)
        assert injected.get(b"x-workspace-id") == expected_ws.encode()
        assert _status_from_sent(sent) == 200

    _run(_inner())


# ─── T6: X-Workspace-ID spoofing is stripped ──────────────────────────────────


def test_t6_workspace_spoofing_stripped():
    from memory_lab.mcp.http_auth import MCPBearerAuthMiddleware

    expected_ws = "cccccccc-0000-0000-0000-000000000003"
    spoofed_ws = "deadbeef-0000-0000-0000-000000000000"

    async def _inner():
        fake = _FakeApp()
        mw = MCPBearerAuthMiddleware(
            fake,
            auth_mode="api_key",
            default_workspace_id="00000000-0000-0000-0000-000000000000",
        )
        scope = _make_scope(
            auth="Bearer stub-valid-token",
            extra_headers=[(b"x-workspace-id", spoofed_ws.encode())],
        )
        sent: list = []

        async def send(m):
            sent.append(m)

        with patch("memory_lab.mcp.http_auth._resolve_workspace_api_key", return_value=expected_ws):
            await mw(scope, _noop_receive, send)

        assert fake.called
        injected = dict(fake.last_headers)
        assert injected.get(b"x-workspace-id") == expected_ws.encode()
        assert injected.get(b"x-workspace-id") != spoofed_ws.encode()

    _run(_inner())


# ─── T7: AUTH=none on non-loopback hard-fails at config level ────────────────


def test_t7_none_auth_nonloopback_hard_fails():
    from memory_lab.mcp import http_config

    with patch.dict(os.environ, {
        "MEMORY_LAB_HTTP_MCP_AUTH": "none",
        "MEMORY_LAB_ENV": "development",
        "MEMORY_LAB_MCP_HTTP_HOST": "0.0.0.0",
    }, clear=False):
        importlib.reload(http_config)
        with pytest.raises(RuntimeError, match="non-loopback"):
            http_config.get_mcp_http_auth_mode()


# ─── T8: Invalid port raises ──────────────────────────────────────────────────


def test_t8_invalid_port_raises():
    from memory_lab.mcp import http_config

    with patch.dict(os.environ, {"MEMORY_LAB_MCP_HTTP_PORT": "notaport"}, clear=False):
        importlib.reload(http_config)
        with pytest.raises(RuntimeError, match="not a valid integer"):
            http_config.get_mcp_http_port()


# ─── T9: AUTH=none without MEMORY_LAB_ENV=development raises ─────────────────


def test_t9_none_auth_without_dev_env_raises():
    from memory_lab.mcp import http_config

    with patch.dict(os.environ, {
        "MEMORY_LAB_HTTP_MCP_AUTH": "none",
        "MEMORY_LAB_ENV": "production",
        "MEMORY_LAB_MCP_HTTP_HOST": "127.0.0.1",
    }, clear=False):
        importlib.reload(http_config)
        with pytest.raises(RuntimeError, match="development"):
            http_config.get_mcp_http_auth_mode()


# ─── T10: _parse_bearer edge cases ───────────────────────────────────────────


def test_t10_parse_bearer_edge_cases():
    from memory_lab.mcp.http_auth import _parse_bearer

    assert _parse_bearer(None) is None
    assert _parse_bearer("") is None
    assert _parse_bearer("bearer") is None
    assert _parse_bearer("Bearer ") is None
    assert _parse_bearer("Token abc") is None
    assert _parse_bearer("Bearer abc123") == "abc123"
    assert _parse_bearer("BEARER MyToken") == "MyToken"
