"""MCP-HTTP-1 smoke tests — import and ASGI app build smoke.

Gate: MCP-HTTP-1
Scope: tests/smoke/test_mcp_http_smoke.py

What is tested (pure import/build smoke, no live DB, no live server):
  S1 — memory_lab.mcp.http_config imports cleanly
  S2 — memory_lab.mcp.http_auth imports cleanly; key classes/functions present
  S3 — memory_lab.mcp.http_server imports cleanly in dev/none-auth mode
  S4 — build_asgi_app() returns a wrapping MCPBearerAuthMiddleware instance
  S5 — http_server._server has all 32 tools registered (same count as server.py)
  S6 — stdio server (server.py) imports cleanly and its tool count is unchanged

No live HTTP. No ephemeral DB. No external network.
pytest.mark.smoke.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.smoke]

_DEV_ENV = {
    "MEMORY_LAB_ENV": "development",
    "MEMORY_LAB_HTTP_MCP_AUTH": "none",
    "MEMORY_LAB_MCP_HTTP_HOST": "127.0.0.1",
    "MEMORY_LAB_MCP_HTTP_PORT": "8765",
}


# ─── S1: http_config imports cleanly ─────────────────────────────────────────


def test_s1_http_config_imports():
    import memory_lab.mcp.http_config as cfg  # noqa: F401

    assert hasattr(cfg, "get_mcp_http_host")
    assert hasattr(cfg, "get_mcp_http_port")
    assert hasattr(cfg, "get_mcp_http_auth_mode")
    assert hasattr(cfg, "get_mcp_http_default_workspace_id")


# ─── S2: http_auth imports cleanly ───────────────────────────────────────────


def test_s2_http_auth_imports():
    import memory_lab.mcp.http_auth as ha  # noqa: F401

    assert hasattr(ha, "MCPBearerAuthMiddleware")
    assert hasattr(ha, "_parse_bearer")
    assert hasattr(ha, "_inject_workspace")
    assert hasattr(ha, "_resolve_workspace_api_key")


# ─── S3: http_server imports cleanly in dev mode ────────────────────────────


def test_s3_http_server_imports_dev_mode():
    with patch.dict(os.environ, _DEV_ENV, clear=False):
        import memory_lab.mcp.http_server as hs
        importlib.reload(hs)
        assert hasattr(hs, "_server")
        assert hasattr(hs, "app")
        assert hasattr(hs, "build_asgi_app")


# ─── S4: build_asgi_app returns MCPBearerAuthMiddleware ──────────────────────


def test_s4_build_asgi_app_returns_middleware():
    from memory_lab.mcp.http_auth import MCPBearerAuthMiddleware

    with patch.dict(os.environ, _DEV_ENV, clear=False):
        import memory_lab.mcp.http_server as hs
        importlib.reload(hs)
        built = hs.build_asgi_app()
        assert isinstance(built, MCPBearerAuthMiddleware)
        assert built.auth_mode == "none"


# ─── S5: http_server has all 32 tools ────────────────────────────────────────


def test_s5_http_server_32_tools():
    with patch.dict(os.environ, _DEV_ENV, clear=False):
        import memory_lab.mcp.http_server as hs
        importlib.reload(hs)

        # FastMCP stores tools in ._tool_manager._tools dict
        tool_mgr = hs._server._tool_manager
        tools = tool_mgr._tools
        assert len(tools) == 32, f"Expected 32 tools on HTTP server, got {len(tools)}: {sorted(tools)}"


# ─── S6: stdio server unchanged ──────────────────────────────────────────────


def test_s6_stdio_server_unchanged():
    import memory_lab.mcp.server as stdio_server
    importlib.reload(stdio_server)

    tool_mgr = stdio_server.server._tool_manager
    tools = tool_mgr._tools
    assert len(tools) == 32, f"Expected 32 tools on stdio server, got {len(tools)}"
    # server.py must not import http_server — transport isolation
    import inspect
    src = inspect.getsource(stdio_server)
    assert "http_server" not in src
    assert "streamable_http_app" not in src
