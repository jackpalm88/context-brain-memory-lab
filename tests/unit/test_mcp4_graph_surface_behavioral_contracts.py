"""MCP-4 Graph Surface Behavioral Contract Tests.

Engineering Quality Asset. Validates behavioral contracts for graph-surface MCP tools.

Tools under test:
  - get_graph_snapshot      :: callable; graph response shape; WS isolation; structured errors
  - list_graph_snapshot     :: callable alias; graph response shape; WS isolation; structured errors
  - load_graph_node_full    :: callable; node response shape; WS isolation; structured errors
  - search_graph_preview    :: callable; preview response shape; WS isolation; structured errors

Contract per tool:
  1. callable without raw exception
  2. success response shape
  3. workspace isolation where applicable
  4. structured error shape: {ok: false, error: {...}}

Scope: graph surface only; reuses MCPHermeticClient and existing fake adapter patterns.
"""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

# Reuse established hermetic MCP/fake patterns without product refactor.
sys.path.insert(0, os.path.dirname(__file__))
from test_mcp2_hub_surface_behavioral_contracts import (  # noqa: E402
    FakeHubApiAdapter,
    FakeHubStore,
    MCPHermeticClient,
    WS_A,
    WS_B,
    _install_ws_aware_auth,
)
from test_mcp3_edge_surface_behavioral_contracts import (  # noqa: E402
    FakeEdgeApiAdapter,
    FakeEdgeStore,
)

from memory_lab.api.main import create_app
import memory_lab.api.routers.edges as edges_router
import memory_lab.api.routers.graph as graph_router
import memory_lab.api.routers.hubs as hubs_router
import memory_lab.mcp.tools as mcp_tools
from memory_lab.mcp.client import MemoryLabApiError

pytestmark = [pytest.mark.unit]

GRAPH_PERMISSIONS = [
    "hubs.create", "hubs.read",
    "edges.create", "edges.read",
    "content.read", "retrieval.search",
]


class FakeGraphApiAdapter:
    """ApiAdapter replacement for graph routes; WS-scoped, in-memory, deterministic."""

    _content: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        cls._content = {}

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @classmethod
    def seed_content(
        cls,
        *,
        workspace_id: str,
        text: str = "graph body",
        quick_summary: str = "graph summary",
        node_type: str = "fact",
        hub_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        content_id = str(uuid.uuid4())
        row = {
            "content_id": content_id,
            "workspace_id": workspace_id,
            "node_type": node_type,
            "quick_summary": quick_summary,
            "memory_type": "semantic",
            "full_text": text,
            "word_count": len(text.split()),
            "created_by_subject": None,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
            "hub_id": hub_id,
        }
        cls._content[content_id] = row
        if hub_id:
            FakeHubStore._links.setdefault(hub_id, []).append(content_id)
        return dict(row)

    def get_graph_snapshot(
        self,
        include_inferred: bool = True,
        include_curated: bool = True,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        nodes = []
        for hub in FakeHubStore().list_hubs(workspace_id=workspace_id):
            nodes.append({
                "hub_id": hub["hub_id"],
                "title": hub["title"],
                "type": hub.get("type"),
                "status": hub.get("status"),
                "workspace_id": hub.get("workspace_uuid") or hub.get("workspace_id"),
            })
        edges = FakeEdgeStore().list_edges(
            workspace_id=workspace_id,
            include_rejected=True,
            include_archived=True,
        )
        if not include_curated:
            edges = [e for e in edges if e.get("origin") != "manual"]
        if not include_inferred:
            edges = [e for e in edges if e.get("origin") == "manual"]
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "content_count": len([
                    r for r in self._content.values()
                    if not workspace_id or r.get("workspace_id") == workspace_id
                ]),
            },
            "filters": {"include_inferred": include_inferred, "include_curated": include_curated},
            "schema_version": "unit-mcp4-v1",
            "workspace_id": workspace_id,
            "limitations": [],
            "warnings": [],
        }

    def load_graph_node_full(self, content_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = self._content.get(content_id)
        if not row:
            return None
        if workspace_id and row.get("workspace_id") != workspace_id:
            return None
        out = dict(row)
        out.pop("hub_id", None)
        return out

    def search_graph_preview(
        self,
        query: str,
        node_type: Optional[str] = None,
        hub_id: Optional[str] = None,
        limit: int = 10,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = (query or "").lower()
        results: List[Dict[str, Any]] = []
        for row in self._content.values():
            if workspace_id and row.get("workspace_id") != workspace_id:
                continue
            if node_type and row.get("node_type") != node_type:
                continue
            if hub_id and row.get("hub_id") != hub_id:
                continue
            haystack = f"{row.get('quick_summary') or ''} {row.get('full_text') or ''}".lower()
            if q not in haystack:
                continue
            results.append({
                "content_id": row["content_id"],
                "node_type": row.get("node_type"),
                "quick_summary": row.get("quick_summary"),
                "hub_match": bool(hub_id and row.get("hub_id") == hub_id),
                "score": 2 if q in (row.get("quick_summary") or "").lower() else 1,
                "load_full_content_recommended": not bool(row.get("quick_summary")),
            })
        results = sorted(results, key=lambda r: (-r["score"], r["content_id"]))[:limit]
        return {"results": results, "count": len(results), "workspace_id": workspace_id}


@pytest.fixture
def hermetic_client_graph(monkeypatch: pytest.MonkeyPatch) -> MCPHermeticClient:
    FakeHubStore.reset()
    FakeEdgeStore.reset()
    FakeGraphApiAdapter.reset()

    app = create_app()
    _install_ws_aware_auth(app, GRAPH_PERMISSIONS)

    monkeypatch.setattr(hubs_router, "ApiAdapter", FakeHubApiAdapter)
    monkeypatch.setattr(hubs_router, "HubStore", FakeHubStore)
    monkeypatch.setattr(hubs_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))
    monkeypatch.setattr(edges_router, "ApiAdapter", FakeEdgeApiAdapter)
    monkeypatch.setattr(edges_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))
    monkeypatch.setattr(graph_router, "ApiAdapter", FakeGraphApiAdapter)
    monkeypatch.setattr(graph_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))

    tc = TestClient(app, raise_server_exceptions=True)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)
    return hc


def _assert_structured_error(result: Dict[str, Any], status_code: Optional[int] = None) -> None:
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"Expected ok=false structured error, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err
    assert "message" in err
    if status_code is not None:
        assert err.get("status_code") == status_code


def _seed_graph_pair() -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    hub_a = mcp_tools.memory_lab_hub_create(title="Graph A", workspace_id=WS_A)
    hub_b = mcp_tools.memory_lab_hub_create(title="Graph B", workspace_id=WS_B)
    assert "hub_id" in hub_a and "hub_id" in hub_b
    content_a = FakeGraphApiAdapter.seed_content(
        workspace_id=WS_A,
        text="alpha graph node body",
        quick_summary="alpha graph preview",
        hub_id=hub_a["hub_id"],
    )
    content_b = FakeGraphApiAdapter.seed_content(
        workspace_id=WS_B,
        text="alpha graph node body for B",
        quick_summary="alpha graph preview B",
        hub_id=hub_b["hub_id"],
    )
    return hub_a, content_a, content_b


class _BrokenSnapshotClient(MCPHermeticClient):
    def __init__(self) -> None:
        pass

    def graph_snapshot(self, *_a: Any, **_kw: Any) -> Dict[str, Any]:
        raise MemoryLabApiError("boom", method="GET", url="/v1/graph/snapshot", status_code=503, body="down")


class _BrokenSearchClient(MCPHermeticClient):
    def __init__(self) -> None:
        pass

    def graph_search_preview(self, *_a: Any, **_kw: Any) -> Dict[str, Any]:
        raise MemoryLabApiError("boom", method="GET", url="/v1/graph/search-preview", status_code=503, body="down")


# G1 get_graph_snapshot

def test_graph_snapshot_G1_1_callable_without_exception(hermetic_client_graph: MCPHermeticClient) -> None:
    result = mcp_tools.get_graph_snapshot(workspace_id=WS_A)
    assert isinstance(result, dict)


def test_graph_snapshot_G1_2_required_success_shape(hermetic_client_graph: MCPHermeticClient) -> None:
    hub_a, _, _ = _seed_graph_pair()
    result = mcp_tools.get_graph_snapshot(workspace_id=WS_A)
    for key in ("nodes", "edges", "stats", "schema_version", "workspace_id"):
        assert key in result, f"{key!r} missing: {result}"
    assert result["workspace_id"] == WS_A
    assert any(n.get("hub_id") == hub_a["hub_id"] for n in result["nodes"])
    assert result["stats"]["node_count"] == len(result["nodes"])


def test_graph_snapshot_G1_3_workspace_isolation(hermetic_client_graph: MCPHermeticClient) -> None:
    hub_a, _, _ = _seed_graph_pair()
    hub_b = mcp_tools.memory_lab_hub_create(title="Only B", workspace_id=WS_B)
    snap_a = mcp_tools.get_graph_snapshot(workspace_id=WS_A)
    ids_a = {n["hub_id"] for n in snap_a["nodes"]}
    assert hub_a["hub_id"] in ids_a
    assert hub_b["hub_id"] not in ids_a


def test_graph_snapshot_G1_4_structured_error_on_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_tools, "_client", lambda: _BrokenSnapshotClient())
    result = mcp_tools.get_graph_snapshot(workspace_id=WS_A)
    _assert_structured_error(result, status_code=503)


# G2 list_graph_snapshot alias

def test_list_graph_snapshot_G2_1_callable_without_exception(hermetic_client_graph: MCPHermeticClient) -> None:
    result = mcp_tools.list_graph_snapshot(workspace_id=WS_A)
    assert isinstance(result, dict)


def test_list_graph_snapshot_G2_2_required_success_shape(hermetic_client_graph: MCPHermeticClient) -> None:
    _seed_graph_pair()
    result = mcp_tools.list_graph_snapshot(include_inferred=False, include_curated=True, workspace_id=WS_A)
    assert "nodes" in result and "edges" in result and "stats" in result
    assert result["filters"] == {"include_inferred": False, "include_curated": True}


def test_list_graph_snapshot_G2_3_workspace_isolation(hermetic_client_graph: MCPHermeticClient) -> None:
    hub_a, _, _ = _seed_graph_pair()
    snap_b = mcp_tools.list_graph_snapshot(workspace_id=WS_B)
    ids_b = {n["hub_id"] for n in snap_b["nodes"]}
    assert hub_a["hub_id"] not in ids_b
    assert all(n.get("workspace_id") == WS_B for n in snap_b["nodes"])


def test_list_graph_snapshot_G2_4_structured_error_on_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_tools, "_client", lambda: _BrokenSnapshotClient())
    result = mcp_tools.list_graph_snapshot(workspace_id=WS_A)
    _assert_structured_error(result, status_code=503)


# G3 load_graph_node_full

def test_load_graph_node_full_G3_1_callable_without_exception(hermetic_client_graph: MCPHermeticClient) -> None:
    _, content_a, _ = _seed_graph_pair()
    result = mcp_tools.load_graph_node_full(content_a["content_id"], workspace_id=WS_A)
    assert isinstance(result, dict)


def test_load_graph_node_full_G3_2_required_success_shape(hermetic_client_graph: MCPHermeticClient) -> None:
    _, content_a, _ = _seed_graph_pair()
    result = mcp_tools.load_graph_node_full(content_a["content_id"], workspace_id=WS_A)
    for key in ("content_id", "workspace_id", "node_type", "quick_summary", "full_text", "word_count"):
        assert key in result, f"{key!r} missing: {result}"
    assert result["content_id"] == content_a["content_id"]
    assert result["workspace_id"] == WS_A


def test_load_graph_node_full_G3_3_workspace_isolation(hermetic_client_graph: MCPHermeticClient) -> None:
    _, content_a, _ = _seed_graph_pair()
    result = mcp_tools.load_graph_node_full(content_a["content_id"], workspace_id=WS_B)
    _assert_structured_error(result, status_code=404)


def test_load_graph_node_full_G3_4_structured_error_on_not_found(hermetic_client_graph: MCPHermeticClient) -> None:
    result = mcp_tools.load_graph_node_full(str(uuid.uuid4()), workspace_id=WS_A)
    _assert_structured_error(result, status_code=404)


# G4 search_graph_preview

def test_search_graph_preview_G4_1_callable_without_exception(hermetic_client_graph: MCPHermeticClient) -> None:
    result = mcp_tools.search_graph_preview("alpha", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_search_graph_preview_G4_2_required_success_shape(hermetic_client_graph: MCPHermeticClient) -> None:
    hub_a, content_a, _ = _seed_graph_pair()
    result = mcp_tools.search_graph_preview("alpha", hub_id=hub_a["hub_id"], workspace_id=WS_A)
    assert "results" in result and "count" in result and "workspace_id" in result
    assert result["workspace_id"] == WS_A
    assert result["count"] == len(result["results"])
    row = next(r for r in result["results"] if r["content_id"] == content_a["content_id"])
    for key in ("content_id", "node_type", "quick_summary", "hub_match", "score", "load_full_content_recommended"):
        assert key in row, f"{key!r} missing: {row}"
    assert row["hub_match"] is True


def test_search_graph_preview_G4_3_workspace_isolation(hermetic_client_graph: MCPHermeticClient) -> None:
    _, content_a, content_b = _seed_graph_pair()
    res_a = mcp_tools.search_graph_preview("alpha", workspace_id=WS_A)
    ids_a = {r["content_id"] for r in res_a["results"]}
    assert content_a["content_id"] in ids_a
    assert content_b["content_id"] not in ids_a


def test_search_graph_preview_G4_4_structured_error_on_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_tools, "_client", lambda: _BrokenSearchClient())
    result = mcp_tools.search_graph_preview("alpha", workspace_id=WS_A)
    _assert_structured_error(result, status_code=503)
