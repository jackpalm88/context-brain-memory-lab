"""MCP-HTTP-1 HTTP transport configuration.

Reads env vars for the streamable-http MCP server.
No DB access. No auth logic. Pure config resolution.
"""
from __future__ import annotations

import os

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def get_mcp_http_host() -> str:
    return os.environ.get("MEMORY_LAB_MCP_HTTP_HOST", "127.0.0.1").strip()


def get_mcp_http_port() -> int:
    raw = os.environ.get("MEMORY_LAB_MCP_HTTP_PORT", "8765").strip()
    try:
        port = int(raw)
    except ValueError:
        raise RuntimeError(f"MEMORY_LAB_MCP_HTTP_PORT is not a valid integer: {raw!r}")
    if not (1 <= port <= 65535):
        raise RuntimeError(f"MEMORY_LAB_MCP_HTTP_PORT out of range: {port}")
    return port


def get_mcp_http_auth_mode() -> str:
    """Return resolved auth mode: 'api_key' or 'none'.

    'none' is only allowed when MEMORY_LAB_ENV=development AND host is loopback.
    Any other combination raises RuntimeError — hard-fail at startup.
    """
    raw = os.environ.get("MEMORY_LAB_HTTP_MCP_AUTH", "api_key").strip().lower() or "api_key"
    if raw not in {"api_key", "none"}:
        raise RuntimeError(f"MEMORY_LAB_HTTP_MCP_AUTH must be 'api_key' or 'none', got: {raw!r}")

    if raw == "none":
        env = os.environ.get("MEMORY_LAB_ENV", "production").strip().lower()
        if env != "development":
            raise RuntimeError(
                "MEMORY_LAB_HTTP_MCP_AUTH=none is only allowed when MEMORY_LAB_ENV=development. "
                f"Current MEMORY_LAB_ENV={env!r}."
            )
        host = get_mcp_http_host()
        if host not in _LOOPBACK_HOSTS:
            raise RuntimeError(
                f"MEMORY_LAB_HTTP_MCP_AUTH=none is not allowed on non-loopback host {host!r}. "
                "Use MEMORY_LAB_HTTP_MCP_AUTH=api_key for network-accessible deployments."
            )

    return raw


def get_mcp_http_default_workspace_id() -> str:
    """Return default workspace_id for dev/none-auth mode from env."""
    return (
        os.environ.get("MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID")
        or os.environ.get("CB_WORKSPACE_ID")
        or "00000000-0000-0000-0000-000000000000"
    )
