"""PR1B minimal MCP server entrypoint (implementation gate only, not executed here)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import APPROVED_TOOLS


server = FastMCP(name="memory-lab-pr1b")

# Register only approved tools from accepted PR1B MCP surface plan.
server.tool()(APPROVED_TOOLS["memory_lab_health"])
server.tool()(APPROVED_TOOLS["memory_lab_content_create_id"])
server.tool()(APPROVED_TOOLS["memory_lab_content_get"])
server.tool()(APPROVED_TOOLS["memory_lab_hub_create"])
server.tool()(APPROVED_TOOLS["memory_lab_hub_get"])
server.tool()(APPROVED_TOOLS["memory_lab_hub_link_content"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_create"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_get"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_list"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_archive"])
server.tool()(APPROVED_TOOLS["memory_lab_retrieval_search"])
server.tool()(APPROVED_TOOLS["create_decision_memory"])
server.tool()(APPROVED_TOOLS["explain_decision"])
server.tool()(APPROVED_TOOLS["list_decisions"])
server.tool()(APPROVED_TOOLS["update_decision_status"])
server.tool()(APPROVED_TOOLS["get_decision_lineage"])
server.tool()(APPROVED_TOOLS["list_decision_conflicts"])
server.tool()(APPROVED_TOOLS["get_decision_timeline"])


if __name__ == "__main__":
    # Not executed in this gate; runtime smoke is a separate approved gate.
    server.run()
