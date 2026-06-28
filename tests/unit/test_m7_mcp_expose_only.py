from pathlib import Path

from memory_lab.api.dependencies.auth import ROLE_PERMISSIONS
from memory_lab.api.main import create_app
from memory_lab.mcp.client import MemoryLabApiClient
from memory_lab.mcp.tools import APPROVED_TOOLS


M7_TOOL_NAMES = {
    "query_memory",
    "list_hubs",
    "update_hub",
    "update_hub_edge",
    "approve_inferred_edge",
    "reject_inferred_edge",
    "save_and_link_to_hub",
    "get_graph_snapshot",
    "list_graph_snapshot",
    "load_graph_node_full",
    "search_graph_preview",
}


def test_m7_tools_are_registered_in_approved_surface_and_server_entrypoint():
    assert M7_TOOL_NAMES.issubset(APPROVED_TOOLS)
    assert len(APPROVED_TOOLS) == 30

    server_source = Path("memory_lab/mcp/server.py").read_text()
    for name in M7_TOOL_NAMES:
        assert f'APPROVED_TOOLS["{name}"]' in server_source


def test_m7_api_routes_and_permissions_are_exposed():
    app = create_app()
    route_keys = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes}

    assert ("/v1/graph/snapshot", ("GET",)) in route_keys
    assert ("/v1/graph/nodes/{content_id}/full", ("GET",)) in route_keys
    assert ("/v1/graph/search-preview", ("GET",)) in route_keys
    assert ("/v1/edges/{edge_id}", ("PATCH",)) in route_keys
    assert ("/v1/edges/inferred/approve", ("POST",)) in route_keys
    assert ("/v1/edges/inferred/reject", ("POST",)) in route_keys
    assert ROLE_PERMISSIONS["edges.update"] == {"owner", "admin", "writer"}


class RecordingClient(MemoryLabApiClient):
    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8000")
        self.calls = []

    def _request(self, method, path, *, params=None, json_body=None, workspace_id=None):
        call = {
            "method": method,
            "path": path,
            "params": params,
            "json_body": json_body,
            "workspace_id": workspace_id,
        }
        self.calls.append(call)
        return call


def test_m7_client_methods_map_to_existing_api_endpoints():
    client = RecordingClient()

    assert client.ask("q")["path"] == "/v1/ask"
    assert client.hub_list()["path"] == "/v1/hubs"
    assert client.hub_update("hub-1", title="New")["method"] == "PATCH"
    assert client.edge_update("edge-1", status="approved")["path"] == "/v1/edges/edge-1"
    assert client.approve_inferred_edge("a", "b", "related")["path"] == "/v1/edges/inferred/approve"
    assert client.reject_inferred_edge("a", "b", "related")["path"] == "/v1/edges/inferred/reject"
    assert client.graph_snapshot()["path"] == "/v1/graph/snapshot"
    assert client.graph_node_full("content-1")["path"] == "/v1/graph/nodes/content-1/full"
    preview = client.graph_search_preview("query", node_type="fact", hub_id="hub-1", limit=3)
    assert preview["path"] == "/v1/graph/search-preview"
    assert preview["params"] == {"query": "query", "limit": 3, "node_type": "fact", "hub_id": "hub-1"}
