"""MCP-HTTP-1 streamable-http MCP server entrypoint.

Exposes the same 32 approved tools as the stdio server (server.py) over
MCP streamable-http transport (MCP spec 2025-11-05).

Key design decisions:
- server.py (stdio) is NOT changed.
- 32 tool registrations are identical to server.py.
- MCPBearerAuthMiddleware wraps the ASGI app for auth.
- Auth mode + host/port resolved from env via http_config.
- ASGI app is importable as `app` for uvicorn/gunicorn mount.
- __main__ block starts uvicorn programmatically for `python -m memory_lab.mcp.http_server`.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .http_auth import MCPBearerAuthMiddleware
from .http_config import (
    get_mcp_http_auth_mode,
    get_mcp_http_default_workspace_id,
    get_mcp_http_host,
    get_mcp_http_port,
)
from .tools import APPROVED_TOOLS

# ── Build FastMCP server (identical tool set to server.py) ────────────────────

_server = FastMCP(name="memory-lab-http")

_server.tool()(APPROVED_TOOLS["memory_lab_health"])
_server.tool()(APPROVED_TOOLS["memory_lab_content_create_id"])
_server.tool()(APPROVED_TOOLS["memory_lab_content_get"])
_server.tool()(APPROVED_TOOLS["list_current_state_anchors"])
_server.tool()(APPROVED_TOOLS["set_quick_summary"])
_server.tool()(APPROVED_TOOLS["update_node_metadata"])
_server.tool()(APPROVED_TOOLS["memory_lab_hub_create"])
_server.tool()(APPROVED_TOOLS["memory_lab_hub_get"])
_server.tool()(APPROVED_TOOLS["memory_lab_hub_link_content"])
_server.tool()(APPROVED_TOOLS["memory_lab_edge_create"])
_server.tool()(APPROVED_TOOLS["memory_lab_edge_get"])
_server.tool()(APPROVED_TOOLS["memory_lab_edge_list"])
_server.tool()(APPROVED_TOOLS["memory_lab_edge_archive"])
_server.tool()(APPROVED_TOOLS["memory_lab_retrieval_search"])
_server.tool()(APPROVED_TOOLS["query_memory"])
_server.tool()(APPROVED_TOOLS["list_hubs"])
_server.tool()(APPROVED_TOOLS["update_hub"])
_server.tool()(APPROVED_TOOLS["update_hub_edge"])
_server.tool()(APPROVED_TOOLS["approve_inferred_edge"])
_server.tool()(APPROVED_TOOLS["reject_inferred_edge"])
_server.tool()(APPROVED_TOOLS["save_and_link_to_hub"])
_server.tool()(APPROVED_TOOLS["get_graph_snapshot"])
_server.tool()(APPROVED_TOOLS["list_graph_snapshot"])
_server.tool()(APPROVED_TOOLS["load_graph_node_full"])
_server.tool()(APPROVED_TOOLS["search_graph_preview"])
_server.tool()(APPROVED_TOOLS["create_decision_memory"])
_server.tool()(APPROVED_TOOLS["explain_decision"])
_server.tool()(APPROVED_TOOLS["list_decisions"])
_server.tool()(APPROVED_TOOLS["update_decision_status"])
_server.tool()(APPROVED_TOOLS["get_decision_lineage"])
_server.tool()(APPROVED_TOOLS["list_decisions_for_content"])
_server.tool()(APPROVED_TOOLS["list_decision_conflicts"])
_server.tool()(APPROVED_TOOLS["get_decision_timeline"])
_server.tool()(APPROVED_TOOLS["classify_content_node"])


def build_asgi_app():
    """Return ASGI app with Bearer auth middleware wrapping the MCP transport.

    Called once at module load time; also re-callable in tests with different env.
    """
    auth_mode = get_mcp_http_auth_mode()
    default_ws = get_mcp_http_default_workspace_id()
    base_app = _server.streamable_http_app()
    return MCPBearerAuthMiddleware(
        base_app,
        auth_mode=auth_mode,
        default_workspace_id=default_ws,
    )


# Module-level ASGI app — for `uvicorn memory_lab.mcp.http_server:app`
app = build_asgi_app()


if __name__ == "__main__":
    import uvicorn  # type: ignore[import-untyped]

    host = get_mcp_http_host()
    port = get_mcp_http_port()
    uvicorn.run(app, host=host, port=port)
