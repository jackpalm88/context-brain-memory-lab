"""PR1B minimal MCP server entrypoint (implementation gate only, not executed here)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import APPROVED_TOOLS


server = FastMCP(name="memory-lab-pr1b")

# Register only approved tools from accepted PR1B MCP surface plan.
server.tool()(APPROVED_TOOLS["memory_lab_health"])
server.tool()(APPROVED_TOOLS["memory_lab_content_create_id"])
server.tool()(APPROVED_TOOLS["memory_lab_content_get"])
server.tool()(APPROVED_TOOLS["list_current_state_anchors"])
server.tool()(APPROVED_TOOLS["set_quick_summary"])
server.tool()(APPROVED_TOOLS["update_node_metadata"])
server.tool()(APPROVED_TOOLS["memory_lab_hub_create"])
server.tool()(APPROVED_TOOLS["memory_lab_hub_get"])
server.tool()(APPROVED_TOOLS["memory_lab_hub_link_content"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_create"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_get"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_list"])
server.tool()(APPROVED_TOOLS["memory_lab_edge_archive"])
server.tool()(APPROVED_TOOLS["memory_lab_retrieval_search"])
server.tool()(APPROVED_TOOLS["query_memory"])
server.tool()(APPROVED_TOOLS["list_hubs"])
server.tool()(APPROVED_TOOLS["update_hub"])
server.tool()(APPROVED_TOOLS["update_hub_edge"])
server.tool()(APPROVED_TOOLS["approve_inferred_edge"])
server.tool()(APPROVED_TOOLS["reject_inferred_edge"])
server.tool()(APPROVED_TOOLS["save_and_link_to_hub"])
server.tool()(APPROVED_TOOLS["get_graph_snapshot"])
server.tool()(APPROVED_TOOLS["list_graph_snapshot"])
server.tool()(APPROVED_TOOLS["load_graph_node_full"])
server.tool()(APPROVED_TOOLS["search_graph_preview"])
server.tool()(APPROVED_TOOLS["create_decision_memory"])
server.tool()(APPROVED_TOOLS["explain_decision"])
server.tool()(APPROVED_TOOLS["list_decisions"])
server.tool()(APPROVED_TOOLS["update_decision_status"])
server.tool()(APPROVED_TOOLS["get_decision_lineage"])
server.tool()(APPROVED_TOOLS["list_decision_conflicts"])
server.tool()(APPROVED_TOOLS["get_decision_timeline"])
server.tool()(APPROVED_TOOLS["classify_content_node"])


if __name__ == "__main__":
    # Not executed in this gate; runtime smoke is a separate approved gate.
    server.run()
