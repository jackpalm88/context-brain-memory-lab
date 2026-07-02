"""MCP-6 Retrieval/Meta Surface Behavioral Contract Tests.

Engineering Quality Asset. Validates behavioral contracts for retrieval/meta MCP tools.

Tools under test (4 — completes 32/32):
  - set_quick_summary         :: callable; updated; WS isolation; structured error
  - update_node_metadata      :: callable; read_only contract; WS isolation; structured error
  - classify_content_node     :: callable; node_type set; WS isolation; structured error on bad type
  - memory_lab_retrieval_search :: callable; response envelope shape; WS isolation; debug flag

Contract per tool:
  1. callable without raw exception
  2. success response shape / semantic contract
  3. workspace isolation
  4. structured error shape: {ok: false, error: {...}}

Pattern: identical to MCP-2/3/4/5 — mcp_tools.<name>(...) via monkeypatched _client.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
from test_mcp2_hub_surface_behavioral_contracts import (  # noqa: E402
    FakeHubApiAdapter,
    FakeHubStore,
    MCPHermeticClient,
    WS_A,
    WS_B,
    SUBJECT,
    _install_ws_aware_auth,
)

from memory_lab.api.main import create_app
import memory_lab.api.routers.content as content_router
import memory_lab.api.routers.retrieval as retrieval_router
import memory_lab.api.routers.hubs as hubs_router
import memory_lab.mcp.tools as mcp_tools
from memory_lab.mcp.client import MemoryLabApiError

pytestmark = [pytest.mark.unit]

META_PERMISSIONS = [
    "hubs.read", "hubs.create",
    "content.read", "content.create", "content.update",
    "retrieval.search",
]

VALID_NODE_TYPES = [
    "decision", "fact", "hypothesis", "question", "playbook",
    "concept", "source", "task", "event", "raw_note",
]


# ---------------------------------------------------------------------------
# Fake adapters
# ---------------------------------------------------------------------------

class FakeContentAdapter:
    """In-memory workspace-scoped content store supporting quick_summary, node_type, metadata."""

    _store: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        cls._store = {}

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @classmethod
    def seed(cls, *, workspace_id: str) -> str:
        cid = str(uuid.uuid4())
        cls._store[f"{workspace_id}:{cid}"] = {
            "content_id": cid,
            "workspace_id": workspace_id,
            "quick_summary": None,
            "node_type": None,
        }
        return cid

    def _get(self, content_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get(f"{workspace_id}:{content_id}")

    # --- content router expects these ---

    def set_quick_summary(self, content_id: str, quick_summary: str,
                          workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        ws = workspace_id or ""
        row = self._get(content_id, ws)
        if row is None:
            return None
        row["quick_summary"] = quick_summary
        return {"content_id": content_id, "quick_summary": quick_summary, "updated": True}

    def get_content_metadata(self, content_id: str,
                             workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        ws = workspace_id or ""
        row = self._get(content_id, ws)
        if row is None:
            return None
        return {
            "content_id": content_id,
            "workspace_id": ws,
            "node_type": row.get("node_type"),
            "quick_summary": row.get("quick_summary"),
            "domain": "general",
            "word_count": 0,
            "created_at": "2024-01-01T00:00:00+00:00",
        }

    def set_node_type(self, content_id: str, node_type: str,
                      workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        ws = workspace_id or ""
        row = self._get(content_id, ws)
        if row is None:
            return None
        row["node_type"] = node_type
        return {"content_id": content_id, "node_type": node_type, "updated": True}

    # --- minimal stubs for other content-router paths (not under test here) ---

    def create_content_minimal(self, content: Optional[str], workspace_id: str,
                               workspace_source: str = "header",
                               created_by_subject: str = SUBJECT) -> Dict[str, Any]:
        cid = str(uuid.uuid4())
        self.__class__._store[f"{workspace_id}:{cid}"] = {
            "content_id": cid,
            "workspace_id": workspace_id,
            "quick_summary": None,
            "node_type": None,
        }
        return {"content_id": cid, "workspace_id": workspace_id, "persisted": True}

    def get_content_minimal(self, content_id: str,
                            workspace_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not workspace_id:
            return None
        return self._get(content_id, workspace_id)


class FakeRetrievalAdapter:
    """Deterministic WS-scoped retrieval search."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def search(self, query: str, workspace_id: Optional[str] = None,
               max_hops: int = 1, min_confidence: float = 0.7,
               graph_boost: float = 0.1,
               memory_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        cid = str(uuid.uuid5(uuid.UUID("00000000-0000-0000-0000-000000000001"),
                              f"{workspace_id}:{query}"))
        return [{
            "content_id": cid,
            "chunk_text": f"deterministic:{workspace_id}:{query[:30]}",
            "final_score": 0.8,
            "retrieval_path": "content_chunk_workspace_scoped",
            "retrieval_mode": "deterministic_fallback",
            "hub_match": None,
            "graph_match": None,
            "knowledge_path": None,
            "retrieval_reason": "deterministic",
            "ranking_reason": None,
            "score_components": {},
            "workspace_id": workspace_id,
        }]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def hermetic_client_meta(monkeypatch: pytest.MonkeyPatch) -> MCPHermeticClient:
    """Hermetic MCP fixture for retrieval/meta surface tests."""
    FakeHubStore.reset()
    FakeContentAdapter.reset()

    app = create_app()
    _install_ws_aware_auth(app, META_PERMISSIONS)

    monkeypatch.setattr(hubs_router, "HubStore", FakeHubStore)
    monkeypatch.setattr(hubs_router, "ApiAdapter", FakeHubApiAdapter)
    monkeypatch.setattr(hubs_router, "get_settings",
                        lambda: type("S", (), {"database_url": "postgresql://unit/hermetic"})())
    monkeypatch.setattr(content_router, "ApiAdapter", FakeContentAdapter)
    monkeypatch.setattr(content_router, "get_settings",
                        lambda: type("S", (), {"database_url": "postgresql://unit/hermetic"})())
    monkeypatch.setattr(retrieval_router, "RetrievalAdapter", FakeRetrievalAdapter)
    monkeypatch.setattr(retrieval_router, "get_settings",
                        lambda: type("S", (), {"database_url": "postgresql://unit/hermetic"})())

    tc = TestClient(app, raise_server_exceptions=True)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)
    return hc


# ---------------------------------------------------------------------------
# M1 — set_quick_summary
# ---------------------------------------------------------------------------

class TestSetQuickSummary:
    def test_m1_callable(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M1.1 — set_quick_summary is callable, returns without raw exception."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.set_quick_summary(
            content_id=cid, quick_summary="A brief summary.", workspace_id=WS_A
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_m1_response_shape(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M1.2 — set_quick_summary returns {content_id, quick_summary, updated}."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.set_quick_summary(
            content_id=cid, quick_summary="Summary text.", workspace_id=WS_A
        )
        assert "content_id" in result, f"Missing content_id: {result}"
        assert "quick_summary" in result, f"Missing quick_summary: {result}"
        assert result["content_id"] == cid
        assert result["quick_summary"] == "Summary text."

    def test_m1_ws_isolation(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M1.3 — set_quick_summary on WS_A content is not accessible from WS_B."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        # WS_B cannot update WS_A content
        result = mcp_tools.set_quick_summary(
            content_id=cid, quick_summary="From WS_B attempt.", workspace_id=WS_B
        )
        assert result.get("ok") is False, (
            f"WS_B must not update WS_A content; expected structured error, got {result}"
        )

    def test_m1_structured_error_on_unknown_id(
            self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M1.4 — set_quick_summary on unknown content_id returns structured error."""
        result = mcp_tools.set_quick_summary(
            content_id=str(uuid.uuid4()),
            quick_summary="Ghost summary.",
            workspace_id=WS_A,
        )
        assert result.get("ok") is False, f"Expected structured error, got {result}"
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# M2 — update_node_metadata (read-only contract)
# ---------------------------------------------------------------------------

class TestUpdateNodeMetadata:
    def test_m2_callable(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M2.1 — update_node_metadata is callable, returns without raw exception."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.update_node_metadata(content_id=cid, workspace_id=WS_A)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_m2_read_only_contract(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M2.2 — update_node_metadata returns read_only=true and mutation='none'."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.update_node_metadata(content_id=cid, workspace_id=WS_A)
        assert result.get("read_only") is True, (
            f"Expected read_only=True in metadata response: {result}"
        )
        assert result.get("mutation") == "none", (
            f"Expected mutation='none' in metadata response: {result}"
        )

    def test_m2_ws_isolation(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M2.3 — WS_A content metadata is not readable from WS_B."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.update_node_metadata(content_id=cid, workspace_id=WS_B)
        assert result.get("ok") is False, (
            f"WS_B must not read WS_A metadata; expected structured error, got {result}"
        )

    def test_m2_structured_error_on_unknown_id(
            self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M2.4 — update_node_metadata on unknown content_id returns structured error."""
        result = mcp_tools.update_node_metadata(
            content_id=str(uuid.uuid4()), workspace_id=WS_A
        )
        assert result.get("ok") is False, f"Expected structured error, got {result}"
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# M3 — classify_content_node
# ---------------------------------------------------------------------------

class TestClassifyContentNode:
    def test_m3_callable(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M3.1 — classify_content_node is callable, returns without raw exception."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.classify_content_node(
            content_id=cid, node_type="fact", workspace_id=WS_A
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_m3_node_type_set(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M3.2 — classify_content_node returns the assigned node_type."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.classify_content_node(
            content_id=cid, node_type="hypothesis", workspace_id=WS_A
        )
        assert "node_type" in result, f"Missing node_type: {result}"
        assert result["node_type"] == "hypothesis", (
            f"Expected hypothesis, got {result.get('node_type')}"
        )

    def test_m3_ws_isolation(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M3.3 — classify WS_A content from WS_B returns structured error."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.classify_content_node(
            content_id=cid, node_type="task", workspace_id=WS_B
        )
        assert result.get("ok") is False, (
            f"WS_B must not classify WS_A content; expected structured error, got {result}"
        )

    def test_m3_structured_error_on_invalid_node_type(
            self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M3.4 — invalid node_type value returns structured error (not raw exception)."""
        cid = FakeContentAdapter.seed(workspace_id=WS_A)
        result = mcp_tools.classify_content_node(
            content_id=cid, node_type="not_a_valid_type", workspace_id=WS_A
        )
        assert result.get("ok") is False, (
            f"Expected structured error for invalid node_type, got {result}"
        )
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# M4 — memory_lab_retrieval_search
# ---------------------------------------------------------------------------

class TestMemoryLabRetrievalSearch:
    def test_m4_callable(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M4.1 — memory_lab_retrieval_search is callable, returns without raw exception."""
        result = mcp_tools.memory_lab_retrieval_search(
            query="memory architecture", workspace_id=WS_A
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_m4_response_envelope_shape(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M4.2 — retrieval_search returns M11C envelope: {query, results, count, limit}."""
        result = mcp_tools.memory_lab_retrieval_search(
            query="retrieval evidence", workspace_id=WS_A
        )
        for field in ("query", "results", "count", "limit"):
            assert field in result, f"Missing field '{field}' in envelope: {result}"
        assert isinstance(result["results"], list), f"results must be a list: {result}"
        assert isinstance(result["count"], int), f"count must be int: {result}"

    def test_m4_ws_isolation(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M4.3 — retrieval results are workspace-scoped (WS_A results differ from WS_B)."""
        r_a = mcp_tools.memory_lab_retrieval_search(
            query="isolation probe", workspace_id=WS_A
        )
        r_b = mcp_tools.memory_lab_retrieval_search(
            query="isolation probe", workspace_id=WS_B
        )
        # Both return valid envelopes
        assert "results" in r_a and "results" in r_b
        # Content is workspace-scoped: chunk_text encodes workspace_id
        texts_a = [r.get("chunk_text", "") for r in r_a["results"]]
        texts_b = [r.get("chunk_text", "") for r in r_b["results"]]
        if texts_a and texts_b:
            assert texts_a != texts_b, (
                f"WS_A and WS_B retrieval must return different content; "
                f"got identical: {texts_a}"
            )

    def test_m4_debug_flag_accepted(self, hermetic_client_meta: MCPHermeticClient) -> None:
        """M4.4 — debug=True is accepted; response includes debug field."""
        result = mcp_tools.memory_lab_retrieval_search(
            query="debug probe", debug=True, workspace_id=WS_A
        )
        assert isinstance(result, dict), f"Expected dict: {result}"
        # 'debug' field must be present (echoed back per M11C envelope contract)
        assert "debug" in result, f"Missing 'debug' in response with debug=True: {result}"
