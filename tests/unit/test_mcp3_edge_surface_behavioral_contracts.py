"""MCP-3 Edge Surface Behavioral Contract Tests.

Engineering Quality Asset. Validates behavioral contracts for edge-surface MCP tools.

Tools under test:
  - memory_lab_edge_create       :: create_edge surface
  - memory_lab_edge_get          :: get_edge surface
  - memory_lab_edge_list         :: list_edges surface
  - memory_lab_edge_archive      :: archive_edge surface
  - update_hub_edge              :: update_edge surface
  - approve_inferred_edge        :: approve_inferred_edge surface
  - reject_inferred_edge         :: reject_inferred_edge surface

Contract per tool:
  1. callable without raw exception
  2. success response shape
  3. workspace isolation where applicable
  4. structured error shape: {ok: false, error: {...}}

Scope: edge surface only; reuses MCP-2 hermetic client and hub fake patterns.
"""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

# Reuse MCP-2 hermetic client / hub fake patterns without product refactor.
sys.path.insert(0, os.path.dirname(__file__))
from test_mcp2_hub_surface_behavioral_contracts import (  # noqa: E402
    FakeHubApiAdapter,
    FakeHubStore,
    MCPHermeticClient,
    SUBJECT,
    WS_A,
    WS_B,
    _install_ws_aware_auth,
)

from memory_lab.api.main import create_app
import memory_lab.api.routers.edges as edges_router
import memory_lab.api.routers.hubs as hubs_router
import memory_lab.mcp.tools as mcp_tools

pytestmark = [pytest.mark.unit]

EDGE_PERMISSIONS = [
    "hubs.create", "hubs.read",
    "edges.create", "edges.read", "edges.update", "edges.archive",
]

VALID_EDGE_TYPES = {"parent", "related", "duplicate", "overlaps", "supports", "part_of", "contradicts"}
VALID_STATUSES = {"inferred", "manual", "approved", "rejected", "needs_review", "archived"}


def _edge_key(source_hub_id: str, target_hub_id: str, edge_type: str) -> str:
    a, b = sorted([source_hub_id, target_hub_id])
    return f"{a}|{b}|{edge_type}"


class FakeEdgeStore:
    """In-memory workspace-scoped edge store. Replaces HubEdgeStore through ApiAdapter."""

    _edges: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        cls._edges = {}

    @staticmethod
    def _now() -> str:
        return "2025-01-01T00:00:00+00:00"

    def _validate_hubs(self, source_hub_id: str, target_hub_id: str, workspace_id: Optional[str]) -> None:
        if not workspace_id:
            return
        if not FakeHubStore().get_hub(source_hub_id, workspace_id=workspace_id):
            raise KeyError("source/target hub not found in workspace")
        if not FakeHubStore().get_hub(target_hub_id, workspace_id=workspace_id):
            raise KeyError("source/target hub not found in workspace")

    def _make_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        *,
        status: str,
        origin: str,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        weight: Optional[float] = None,
        created_by: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if edge_type not in VALID_EDGE_TYPES:
            raise ValueError(f"Invalid type '{edge_type}'")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'")
        self._validate_hubs(source_hub_id, target_hub_id, workspace_id)
        edge_id = str(uuid.uuid4())
        row = {
            "id": edge_id,
            "source_hub_id": source_hub_id,
            "target_hub_id": target_hub_id,
            "workspace_id": workspace_id,
            "type": edge_type,
            "status": status,
            "origin": origin,
            "confidence": confidence,
            "reason": reason,
            "note": note,
            "weight": weight,
            "edge_key": _edge_key(source_hub_id, target_hub_id, edge_type),
            "created_by": created_by,
            "created_at": self._now(),
            "updated_at": self._now(),
            "archived_at": None,
        }
        self.__class__._edges[edge_id] = row
        return dict(row)

    def create_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        status: str = "manual",
        origin: str = "manual",
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        weight: Optional[float] = None,
        created_by: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._make_edge(
            source_hub_id, target_hub_id, edge_type,
            status=status, origin=origin, confidence=confidence, reason=reason,
            note=note, weight=weight, created_by=created_by, workspace_id=workspace_id,
        )

    def get_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = self.__class__._edges.get(edge_id)
        if not row:
            return None
        if workspace_id and row.get("workspace_id") != workspace_id:
            return None
        return dict(row)

    def list_edges(
        self,
        hub_id: Optional[str] = None,
        include_rejected: bool = False,
        include_archived: bool = False,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        result = []
        for row in self.__class__._edges.values():
            if workspace_id and row.get("workspace_id") != workspace_id:
                continue
            if hub_id and hub_id not in (row.get("source_hub_id"), row.get("target_hub_id")):
                continue
            if not include_archived and row.get("archived_at") is not None:
                continue
            if not include_rejected and row.get("status") == "rejected":
                continue
            result.append(dict(row))
        return result

    def update_edge(self, edge_id: str, updates: Dict[str, Any], workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = self.get_edge(edge_id, workspace_id=workspace_id)
        if not row:
            return None
        fields = {k: v for k, v in updates.items() if k in {"type", "status", "note", "reason", "confidence"}}
        if "type" in fields and fields["type"] not in VALID_EDGE_TYPES:
            raise ValueError(f"Invalid type '{fields['type']}'")
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{fields['status']}'")
        self.__class__._edges[edge_id].update(fields)
        self.__class__._edges[edge_id]["updated_at"] = self._now()
        return self.get_edge(edge_id, workspace_id=workspace_id)

    def archive_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = self.get_edge(edge_id, workspace_id=workspace_id)
        if not row or row.get("archived_at") is not None:
            return None
        self.__class__._edges[edge_id]["status"] = "archived"
        self.__class__._edges[edge_id]["archived_at"] = self._now()
        self.__class__._edges[edge_id]["updated_at"] = self._now()
        return self.get_edge(edge_id, workspace_id=workspace_id)

    def approve_inferred_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._upsert_review(
            source_hub_id, target_hub_id, edge_type,
            status="approved", origin="inferred_approved", reason=reason,
            confidence=confidence, note=note, created_by=created_by, workspace_id=workspace_id,
        )

    def reject_inferred_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._upsert_review(
            source_hub_id, target_hub_id, edge_type,
            status="rejected", origin="inferred_rejected", reason=reason,
            note=note, created_by=created_by, workspace_id=workspace_id,
        )

    def _upsert_review(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        *,
        status: str,
        origin: str,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._validate_hubs(source_hub_id, target_hub_id, workspace_id)
        key = _edge_key(source_hub_id, target_hub_id, edge_type)
        for edge_id, row in self.__class__._edges.items():
            if row.get("edge_key") == key and row.get("archived_at") is None:
                row.update({"status": status, "origin": origin, "reason": reason, "note": note,
                            "confidence": confidence, "updated_at": self._now()})
                return dict(row)
        return self._make_edge(
            source_hub_id, target_hub_id, edge_type,
            status=status, origin=origin, reason=reason, confidence=confidence,
            note=note, created_by=created_by, workspace_id=workspace_id,
        )


class FakeEdgeApiAdapter:
    """ApiAdapter replacement for edge routes; delegates to FakeEdgeStore."""

    def __init__(self, database_url: str) -> None:
        self.hub_edge_store = FakeEdgeStore()

    def create_edge(self, payload: Dict[str, Any], workspace_id: Optional[str] = None, created_by: Optional[str] = None) -> Dict[str, Any]:
        return self.hub_edge_store.create_edge(
            source_hub_id=payload["source_hub_id"],
            target_hub_id=payload["target_hub_id"],
            edge_type=payload["edge_type"],
            status=payload.get("status", "manual"),
            origin=payload.get("origin", "manual"),
            confidence=payload.get("confidence"),
            reason=payload.get("reason"),
            note=payload.get("note"),
            created_by=created_by,
            workspace_id=workspace_id,
        )

    def get_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.get_edge(edge_id, workspace_id=workspace_id)

    def list_edges(self, hub_id: Optional[str], include_archived: bool, include_rejected: bool, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.hub_edge_store.list_edges(hub_id, include_rejected, include_archived, workspace_id=workspace_id)

    def archive_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.archive_edge(edge_id, workspace_id=workspace_id)

    def update_edge(self, edge_id: str, updates: Dict[str, Any], workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.update_edge(edge_id, updates, workspace_id=workspace_id)

    def approve_inferred_edge(self, **kwargs: Any) -> Dict[str, Any]:
        return self.hub_edge_store.approve_inferred_edge(**kwargs)

    def reject_inferred_edge(self, **kwargs: Any) -> Dict[str, Any]:
        return self.hub_edge_store.reject_inferred_edge(**kwargs)


@pytest.fixture
def hermetic_client_edges(monkeypatch: pytest.MonkeyPatch) -> MCPHermeticClient:
    FakeHubStore.reset()
    FakeEdgeStore.reset()
    app = create_app()
    _install_ws_aware_auth(app, EDGE_PERMISSIONS)

    monkeypatch.setattr(hubs_router, "ApiAdapter", FakeHubApiAdapter)
    monkeypatch.setattr(hubs_router, "HubStore", FakeHubStore)
    monkeypatch.setattr(hubs_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))
    monkeypatch.setattr(edges_router, "ApiAdapter", FakeEdgeApiAdapter)
    monkeypatch.setattr(edges_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))

    tc = TestClient(app, raise_server_exceptions=True)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)
    return hc


def _hub_pair(workspace_id: str = WS_A) -> tuple[Dict[str, Any], Dict[str, Any]]:
    a = mcp_tools.memory_lab_hub_create(title=f"source {uuid.uuid4()}", workspace_id=workspace_id)
    b = mcp_tools.memory_lab_hub_create(title=f"target {uuid.uuid4()}", workspace_id=workspace_id)
    assert "hub_id" in a and "hub_id" in b
    return a, b


def _edge(workspace_id: str = WS_A) -> Dict[str, Any]:
    a, b = _hub_pair(workspace_id)
    edge = mcp_tools.memory_lab_edge_create(a["hub_id"], b["hub_id"], "related", workspace_id=workspace_id)
    assert "id" in edge
    return edge


def _assert_structured_error(result: Dict[str, Any], status_code: Optional[int] = None) -> None:
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"Expected ok=false structured error, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err
    assert "message" in err
    if status_code is not None:
        assert err.get("status_code") == status_code


# H1 create_edge

def test_create_edge_E1_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.memory_lab_edge_create(a["hub_id"], b["hub_id"], "related", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_create_edge_E1_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.memory_lab_edge_create(a["hub_id"], b["hub_id"], "supports", workspace_id=WS_A)
    for key in ("id", "source_hub_id", "target_hub_id", "type", "status", "origin"):
        assert key in result, f"{key!r} missing: {result}"
    assert result["source_hub_id"] == a["hub_id"]
    assert result["target_hub_id"] == b["hub_id"]
    assert result["type"] == "supports"
    assert result["status"] == "manual"


def test_create_edge_E1_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.memory_lab_edge_create(a["hub_id"], b["hub_id"], "related", workspace_id=WS_B)
    _assert_structured_error(result, status_code=404)


def test_create_edge_E1_4_structured_error_on_invalid_hub(hermetic_client_edges: MCPHermeticClient) -> None:
    a, _ = _hub_pair(WS_A)
    result = mcp_tools.memory_lab_edge_create(a["hub_id"], str(uuid.uuid4()), "related", workspace_id=WS_A)
    _assert_structured_error(result, status_code=404)


# H2 get_edge

def test_get_edge_E2_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_get(edge["id"], workspace_id=WS_A)
    assert isinstance(result, dict)


def test_get_edge_E2_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_get(edge["id"], workspace_id=WS_A)
    for key in ("id", "source_hub_id", "target_hub_id", "type", "status"):
        assert key in result, f"{key!r} missing: {result}"
    assert result["id"] == edge["id"]


def test_get_edge_E2_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_get(edge["id"], workspace_id=WS_B)
    _assert_structured_error(result, status_code=404)


def test_get_edge_E2_4_structured_error_on_not_found(hermetic_client_edges: MCPHermeticClient) -> None:
    result = mcp_tools.memory_lab_edge_get(str(uuid.uuid4()), workspace_id=WS_A)
    _assert_structured_error(result, status_code=404)


# H3 list_edges

def test_list_edges_E3_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    result = mcp_tools.memory_lab_edge_list(workspace_id=WS_A)
    assert isinstance(result, dict)


def test_list_edges_E3_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_list(workspace_id=WS_A)
    assert "edges" in result and "count" in result
    assert any(e.get("id") == edge["id"] for e in result["edges"])
    assert result["count"] == len(result["edges"])


def test_list_edges_E3_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    edge_a = _edge(WS_A)
    edge_b = _edge(WS_B)
    list_a = mcp_tools.memory_lab_edge_list(workspace_id=WS_A)
    list_b = mcp_tools.memory_lab_edge_list(workspace_id=WS_B)
    ids_a = {e["id"] for e in list_a["edges"]}
    ids_b = {e["id"] for e in list_b["edges"]}
    assert edge_a["id"] in ids_a and edge_b["id"] not in ids_a
    assert edge_b["id"] in ids_b and edge_a["id"] not in ids_b


def test_list_edges_E3_4_empty_list_is_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    result = mcp_tools.memory_lab_edge_list(workspace_id=WS_A)
    assert result.get("edges") == []
    assert result.get("count") == 0


# H4 archive_edge

def test_archive_edge_E4_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_archive(edge["id"], workspace_id=WS_A)
    assert isinstance(result, dict)


def test_archive_edge_E4_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_archive(edge["id"], workspace_id=WS_A)
    assert result.get("archived") is True
    assert result.get("edge_id") == edge["id"]
    assert result.get("edge", {}).get("status") == "archived"


def test_archive_edge_E4_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.memory_lab_edge_archive(edge["id"], workspace_id=WS_B)
    _assert_structured_error(result, status_code=404)
    own = mcp_tools.memory_lab_edge_get(edge["id"], workspace_id=WS_A)
    assert own.get("status") == "manual"


def test_archive_edge_E4_4_structured_error_on_not_found(hermetic_client_edges: MCPHermeticClient) -> None:
    result = mcp_tools.memory_lab_edge_archive(str(uuid.uuid4()), workspace_id=WS_A)
    _assert_structured_error(result, status_code=404)


# H5 update_edge / update_hub_edge

def test_update_edge_E5_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.update_hub_edge(edge["id"], note="updated", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_update_edge_E5_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.update_hub_edge(edge["id"], status="needs_review", note="review", workspace_id=WS_A)
    assert result.get("updated") is True
    assert "edge" in result
    assert result["edge"]["id"] == edge["id"]
    assert result["edge"]["status"] == "needs_review"
    assert result["edge"]["note"] == "review"


def test_update_edge_E5_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    edge = _edge(WS_A)
    result = mcp_tools.update_hub_edge(edge["id"], note="hijack", workspace_id=WS_B)
    _assert_structured_error(result, status_code=404)
    own = mcp_tools.memory_lab_edge_get(edge["id"], workspace_id=WS_A)
    assert own.get("note") is None


def test_update_edge_E5_4_structured_error_on_not_found(hermetic_client_edges: MCPHermeticClient) -> None:
    result = mcp_tools.update_hub_edge(str(uuid.uuid4()), note="ghost", workspace_id=WS_A)
    _assert_structured_error(result, status_code=404)


# H6 approve_inferred_edge

def test_approve_inferred_E6_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.approve_inferred_edge(a["hub_id"], b["hub_id"], "related", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_approve_inferred_E6_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.approve_inferred_edge(
        a["hub_id"], b["hub_id"], "related", reason="ok", confidence=0.9, workspace_id=WS_A
    )
    assert result.get("approved") is True
    assert "edge" in result
    edge = result["edge"]
    assert edge["status"] == "approved"
    assert edge["origin"] == "inferred_approved"
    assert edge["confidence"] == 0.9


def test_approve_inferred_E6_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.approve_inferred_edge(a["hub_id"], b["hub_id"], "related", workspace_id=WS_B)
    _assert_structured_error(result, status_code=409)


def test_approve_inferred_E6_4_structured_error_on_invalid_hub(hermetic_client_edges: MCPHermeticClient) -> None:
    a, _ = _hub_pair(WS_A)
    result = mcp_tools.approve_inferred_edge(a["hub_id"], str(uuid.uuid4()), "related", workspace_id=WS_A)
    _assert_structured_error(result, status_code=409)


# H7 reject_inferred_edge

def test_reject_inferred_E7_1_callable_without_exception(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.reject_inferred_edge(a["hub_id"], b["hub_id"], "related", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_reject_inferred_E7_2_required_success_shape(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.reject_inferred_edge(a["hub_id"], b["hub_id"], "related", reason="no", workspace_id=WS_A)
    assert result.get("rejected") is True
    assert "edge" in result
    edge = result["edge"]
    assert edge["status"] == "rejected"
    assert edge["origin"] == "inferred_rejected"
    assert edge["reason"] == "no"


def test_reject_inferred_E7_3_workspace_isolation(hermetic_client_edges: MCPHermeticClient) -> None:
    a, b = _hub_pair(WS_A)
    result = mcp_tools.reject_inferred_edge(a["hub_id"], b["hub_id"], "related", workspace_id=WS_B)
    _assert_structured_error(result, status_code=409)


def test_reject_inferred_E7_4_structured_error_on_invalid_hub(hermetic_client_edges: MCPHermeticClient) -> None:
    a, _ = _hub_pair(WS_A)
    result = mcp_tools.reject_inferred_edge(a["hub_id"], str(uuid.uuid4()), "related", workspace_id=WS_A)
    _assert_structured_error(result, status_code=409)
