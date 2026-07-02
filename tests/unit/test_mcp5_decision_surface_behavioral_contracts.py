"""MCP-5 Decision Surface Behavioral Contract Tests.

Engineering Quality Asset. Validates behavioral contracts for decision-surface MCP tools.

Tools under test:
  - create_decision_memory   :: callable; response shape; WS isolation; structured errors
  - explain_decision         :: callable; full response shape; WS isolation; structured errors
  - list_decisions           :: callable; list response shape; WS isolation; structured errors
  - update_decision_status   :: callable; updated status returned; WS isolation; structured errors
  - get_decision_lineage     :: callable; lineage response shape; WS isolation; structured errors
  - list_decision_conflicts  :: callable; conflicts response shape; WS isolation; structured errors
  - get_decision_timeline    :: callable; timeline response shape; WS isolation; structured errors

Contract per tool:
  1. callable without raw exception
  2. success response shape
  3. workspace isolation where applicable
  4. structured error shape: {ok: false, error: {...}}

Scope: decision surface only; reuses MCPHermeticClient and existing fake adapter patterns.
Tools are invoked via mcp_tools.<name>(...) after monkeypatching _client (identical to MCP-2/3/4 pattern).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
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
import memory_lab.api.routers.decisions as decisions_router
import memory_lab.api.routers.hubs as hubs_router
import memory_lab.mcp.tools as mcp_tools
from memory_lab.mcp.client import MemoryLabApiError
from memory_lab.decisions import (
    DecisionCreate,
    DecisionCreateResponse,
    DecisionFull,
    DecisionListResponse,
    DecisionLineageResponse,
    DecisionConflictsResponse,
    DecisionTimelineResponse,
    DecisionSummary,
    LineageNode,
    ConflictPair,
)

pytestmark = [pytest.mark.unit]

DECISION_PERMISSIONS = [
    "hubs.read", "hubs.create",
    "decisions.create", "decisions.read", "decisions.update",
]

_NOW = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _make_summary(decision_id: str, title: str, status: str = "active") -> DecisionSummary:
    return DecisionSummary(
        decision_id=decision_id,
        title=title,
        decision_status=status,
        reversible=True,
        confidence_level="medium",
        decision_tags=[],
        created_by_subject=SUBJECT,
        created_at=_NOW,
    )


def _make_full(decision_id: str, title: str, reason: str, status: str = "active") -> DecisionFull:
    return DecisionFull(
        decision_id=decision_id,
        content_id=None,
        title=title,
        decision_reason=reason,
        decision_context=None,
        why_this_matters=None,
        decision_status=status,
        reversible=True,
        source_content_ids=[],
        linked_hub_ids=[],
        supersedes_decision_id=None,
        superseded_by_decision_id=None,
        alternatives_considered=[],
        contradicting_evidence=None,
        confidence_level="medium",
        decision_tags=[],
        created_by_subject=SUBJECT,
        created_at=_NOW,
        updated_at=_NOW,
    )


class FakeDecisionStore:
    """In-memory WS-scoped DecisionStore replacement."""

    _store: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        cls._store = {}

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @classmethod
    def _key(cls, decision_id: str, workspace_id: str) -> str:
        return f"{workspace_id}:{decision_id}"

    @classmethod
    def seed(cls, *, workspace_id: str, title: str, reason: str = "seeded reason",
             status: str = "active", tags: Optional[List[str]] = None,
             linked_hub_ids: Optional[List[str]] = None) -> str:
        did = str(uuid.uuid4())
        cls._store[cls._key(did, workspace_id)] = {
            "decision_id": did,
            "workspace_id": workspace_id,
            "title": title,
            "decision_reason": reason,
            "decision_status": status,
            "decision_tags": tags or [],
            "linked_hub_ids": linked_hub_ids or [],
            "reversible": True,
            "confidence_level": "medium",
            "created_by_subject": SUBJECT,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        return did

    def _get_raw(self, decision_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get(self._key(decision_id, workspace_id))

    def create_decision(self, payload: DecisionCreate, workspace_id: str,
                        created_by_subject: str) -> Dict[str, Any]:
        did = str(uuid.uuid4())
        row: Dict[str, Any] = {
            "decision_id": did,
            "workspace_id": workspace_id,
            "title": payload.title,
            "decision_reason": payload.decision_reason,
            "decision_status": payload.decision_status,
            "decision_tags": list(payload.decision_tags),
            "linked_hub_ids": [str(h) for h in payload.linked_hub_ids],
            "reversible": payload.reversible,
            "confidence_level": payload.confidence_level,
            "created_by_subject": created_by_subject,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        self._store[self._key(did, workspace_id)] = row
        return row

    def explain_decision(self, decision_id: Any, workspace_id: str) -> DecisionFull:
        row = self._get_raw(str(decision_id), workspace_id)
        if row is None:
            raise KeyError(f"decision {decision_id} not found")
        return _make_full(row["decision_id"], row["title"], row["decision_reason"],
                          row["decision_status"])

    def list_decisions(self, status: Optional[str], hub_id: Optional[Any],
                       limit: int, workspace_id: str) -> DecisionListResponse:
        items = [
            v for v in self._store.values()
            if v["workspace_id"] == workspace_id
            and (status is None or v["decision_status"] == status)
        ][:limit]
        summaries = [_make_summary(v["decision_id"], v["title"], v["decision_status"])
                     for v in items]
        return DecisionListResponse(decisions=summaries, count=len(summaries))

    def update_status(self, decision_id: Any, decision_status: str,
                      workspace_id: str) -> DecisionFull:
        row = self._get_raw(str(decision_id), workspace_id)
        if row is None:
            raise KeyError(f"decision {decision_id} not found")
        row["decision_status"] = decision_status
        return _make_full(row["decision_id"], row["title"], row["decision_reason"],
                          decision_status)

    def get_lineage(self, decision_id: Any, workspace_id: str) -> DecisionLineageResponse:
        row = self._get_raw(str(decision_id), workspace_id)
        if row is None:
            raise KeyError(f"decision {decision_id} not found")
        return DecisionLineageResponse(
            decision_id=row["decision_id"],
            title=row["title"],
            ancestors=[],
            descendants=[],
            depth=0,
            depth_limit_reached=False,
        )

    def list_conflicts(self, workspace_id: str) -> DecisionConflictsResponse:
        items = [v for v in self._store.values()
                 if v["workspace_id"] == workspace_id
                 and v["decision_status"] == "active"]
        from collections import defaultdict
        hub_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for v in items:
            for h in v.get("linked_hub_ids", []):
                hub_map[h].append(v)
        pairs: List[ConflictPair] = []
        for h, members in hub_map.items():
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    pairs.append(ConflictPair(
                        decision_a=LineageNode(
                            decision_id=a["decision_id"], title=a["title"],
                            decision_status=a["decision_status"],
                            created_by_subject=SUBJECT, created_at=_NOW),
                        decision_b=LineageNode(
                            decision_id=b["decision_id"], title=b["title"],
                            decision_status=b["decision_status"],
                            created_by_subject=SUBJECT, created_at=_NOW),
                        conflict_reason=f"Same hub_id: {h}",
                    ))
        return DecisionConflictsResponse(conflicts=pairs, count=len(pairs))

    def get_timeline(self, hub_id: Optional[Any], tags: Optional[str],
                     limit: int, workspace_id: str) -> DecisionTimelineResponse:
        items = [v for v in self._store.values() if v["workspace_id"] == workspace_id]
        by_status: Dict[str, List[DecisionSummary]] = {
            "active": [], "superseded": [], "reversed": [], "draft": []
        }
        for v in items[:limit]:
            s = v["decision_status"]
            if s in by_status:
                by_status[s].append(_make_summary(v["decision_id"], v["title"], s))
        return DecisionTimelineResponse(
            active=by_status["active"],
            superseded=by_status["superseded"],
            reversed=by_status["reversed"],
            draft=by_status["draft"],
            total=sum(len(lst) for lst in by_status.values()),
        )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def hermetic_client_decisions(monkeypatch: pytest.MonkeyPatch) -> MCPHermeticClient:
    """Hermetic MCP fixture for decision surface tests.

    Wires MCPHermeticClient to FastAPI TestClient with FakeDecisionStore.
    Tools are invoked via mcp_tools.<name>(...) after monkeypatching _client.
    """
    FakeHubStore.reset()
    FakeDecisionStore.reset()

    app = create_app()
    _install_ws_aware_auth(app, DECISION_PERMISSIONS)

    monkeypatch.setattr(hubs_router, "HubStore", FakeHubStore)
    monkeypatch.setattr(hubs_router, "ApiAdapter", FakeHubApiAdapter)
    monkeypatch.setattr(hubs_router, "get_settings",
                        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))
    monkeypatch.setattr(decisions_router, "DecisionStore", FakeDecisionStore)
    monkeypatch.setattr(decisions_router, "get_settings",
                        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"))

    tc = TestClient(app, raise_server_exceptions=True)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)
    return hc


# ---------------------------------------------------------------------------
# D1 — create_decision_memory
# ---------------------------------------------------------------------------

class TestCreateDecisionMemory:
    def test_d1_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D1.1 — create_decision_memory is callable, returns without raw exception."""
        result = mcp_tools.create_decision_memory(
            title="Use PostgreSQL",
            decision_reason="ACID compliance needed",
            workspace_id=WS_A,
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d1_response_shape(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D1.2 — create_decision_memory returns expected fields."""
        result = mcp_tools.create_decision_memory(
            title="Cache Strategy",
            decision_reason="Reduce DB load",
            workspace_id=WS_A,
        )
        assert "decision_id" in result, f"Missing decision_id: {result}"
        assert "title" in result, f"Missing title: {result}"
        assert "decision_status" in result, f"Missing decision_status: {result}"
        assert result["title"] == "Cache Strategy"

    def test_d1_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D1.3 — decision created in WS_A is not listed from WS_B."""
        mcp_tools.create_decision_memory(
            title="WS_A Decision",
            decision_reason="reason",
            workspace_id=WS_A,
        )
        listed_b = mcp_tools.list_decisions(workspace_id=WS_B)
        ids_b = [d["decision_id"] for d in listed_b.get("decisions", [])]
        assert len(ids_b) == 0, f"WS_B must not see WS_A decisions; got {ids_b}"

    def test_d1_structured_error_on_missing_reason(
            self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D1.4 — missing required field (decision_reason) returns structured error."""
        result = mcp_tools.create_decision_memory(
            title="Missing reason",
            decision_reason="",   # empty — violates min_length=1
            workspace_id=WS_A,
        )
        assert result.get("ok") is False, f"Expected structured error, got {result}"
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# D2 — explain_decision
# ---------------------------------------------------------------------------

class TestExplainDecision:
    def test_d2_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D2.1 — explain_decision is callable, returns without raw exception."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Explain Me", reason="because")
        result = mcp_tools.explain_decision(decision_id=did, workspace_id=WS_A)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d2_response_shape(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D2.2 — explain_decision returns DecisionFull-shaped response."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Shape Decision",
                                     reason="shape reason")
        result = mcp_tools.explain_decision(decision_id=did, workspace_id=WS_A)
        for field in ("decision_id", "title", "decision_reason", "decision_status",
                      "reversible", "confidence_level"):
            assert field in result, f"Missing field '{field}': {result}"
        assert result["decision_id"] == did

    def test_d2_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D2.3 — WS_A decision is not readable from WS_B."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Private Decision",
                                     reason="secret")
        result = mcp_tools.explain_decision(decision_id=did, workspace_id=WS_B)
        assert result.get("ok") is False, (
            f"WS_B must not explain WS_A decision; expected structured error, got {result}"
        )

    def test_d2_structured_error_on_missing_id(
            self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D2.4 — explain_decision with unknown ID returns structured error."""
        result = mcp_tools.explain_decision(
            decision_id=str(uuid.uuid4()), workspace_id=WS_A
        )
        assert result.get("ok") is False, f"Expected structured error, got {result}"
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# D3 — list_decisions
# ---------------------------------------------------------------------------

class TestListDecisions:
    def test_d3_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D3.1 — list_decisions is callable, returns without raw exception."""
        result = mcp_tools.list_decisions(workspace_id=WS_A)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d3_response_shape(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D3.2 — list_decisions returns {decisions: [...], count: N}."""
        FakeDecisionStore.seed(workspace_id=WS_A, title="Listed", reason="reason")
        result = mcp_tools.list_decisions(workspace_id=WS_A)
        assert "decisions" in result, f"Missing 'decisions': {result}"
        assert "count" in result, f"Missing 'count': {result}"
        assert isinstance(result["decisions"], list)
        assert result["count"] >= 1

    def test_d3_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D3.3 — decisions created in WS_A are not listed from WS_B."""
        FakeDecisionStore.seed(workspace_id=WS_A, title="A-Only", reason="reason")
        result_b = mcp_tools.list_decisions(workspace_id=WS_B)
        assert result_b["count"] == 0, (
            f"WS_B must not see WS_A decisions; got count={result_b['count']}"
        )

    def test_d3_status_filter(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D3.4 — list_decisions status filter returns only matching status."""
        FakeDecisionStore.seed(workspace_id=WS_A, title="Active One", reason="r",
                               status="active")
        FakeDecisionStore.seed(workspace_id=WS_A, title="Draft One", reason="r",
                               status="draft")
        result = mcp_tools.list_decisions(status="active", workspace_id=WS_A)
        statuses = {d["decision_status"] for d in result.get("decisions", [])}
        assert not statuses - {"active"}, (
            f"Filter returned non-active decisions: {statuses}"
        )


# ---------------------------------------------------------------------------
# D4 — update_decision_status
# ---------------------------------------------------------------------------

class TestUpdateDecisionStatus:
    def test_d4_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D4.1 — update_decision_status is callable, returns without raw exception."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Updatable", reason="reason")
        result = mcp_tools.update_decision_status(
            decision_id=did, decision_status="superseded", workspace_id=WS_A
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d4_status_updated(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D4.2 — update_decision_status returns the updated status in response."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="To Supersede", reason="reason")
        result = mcp_tools.update_decision_status(
            decision_id=did, decision_status="superseded", workspace_id=WS_A
        )
        assert result.get("decision_status") == "superseded", (
            f"Expected superseded, got {result.get('decision_status')}"
        )

    def test_d4_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D4.3 — cannot update WS_A decision status from WS_B."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Isolated Update",
                                     reason="reason")
        result = mcp_tools.update_decision_status(
            decision_id=did, decision_status="reversed", workspace_id=WS_B
        )
        assert result.get("ok") is False, (
            f"WS_B must not update WS_A decision; expected structured error, got {result}"
        )

    def test_d4_structured_error_on_unknown_id(
            self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D4.4 — update on unknown ID returns structured error."""
        result = mcp_tools.update_decision_status(
            decision_id=str(uuid.uuid4()),
            decision_status="reversed",
            workspace_id=WS_A,
        )
        assert result.get("ok") is False, f"Expected structured error, got {result}"
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# D5 — get_decision_lineage
# ---------------------------------------------------------------------------

class TestGetDecisionLineage:
    def test_d5_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D5.1 — get_decision_lineage is callable, returns without raw exception."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Lineage Root", reason="reason")
        result = mcp_tools.get_decision_lineage(decision_id=did, workspace_id=WS_A)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d5_response_shape(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D5.2 — get_decision_lineage returns lineage-shaped response."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Lineage Shape", reason="reason")
        result = mcp_tools.get_decision_lineage(decision_id=did, workspace_id=WS_A)
        for field in ("decision_id", "title", "ancestors", "descendants", "depth"):
            assert field in result, f"Missing field '{field}': {result}"
        assert result["decision_id"] == did
        assert isinstance(result["ancestors"], list)
        assert isinstance(result["descendants"], list)

    def test_d5_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D5.3 — WS_A decision lineage is not readable from WS_B."""
        did = FakeDecisionStore.seed(workspace_id=WS_A, title="Private Lineage",
                                     reason="reason")
        result = mcp_tools.get_decision_lineage(decision_id=did, workspace_id=WS_B)
        assert result.get("ok") is False, (
            f"WS_B must not read WS_A lineage; expected structured error, got {result}"
        )

    def test_d5_structured_error_on_unknown_id(
            self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D5.4 — lineage for unknown ID returns structured error."""
        result = mcp_tools.get_decision_lineage(
            decision_id=str(uuid.uuid4()), workspace_id=WS_A
        )
        assert result.get("ok") is False, f"Expected structured error, got {result}"
        assert "error" in result, f"Missing 'error' key: {result}"


# ---------------------------------------------------------------------------
# D6 — list_decision_conflicts
# ---------------------------------------------------------------------------

class TestListDecisionConflicts:
    def test_d6_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D6.1 — list_decision_conflicts is callable, returns without raw exception."""
        result = mcp_tools.list_decision_conflicts(workspace_id=WS_A)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d6_response_shape(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D6.2 — list_decision_conflicts returns {conflicts: [...], count: N}."""
        result = mcp_tools.list_decision_conflicts(workspace_id=WS_A)
        assert "conflicts" in result, f"Missing 'conflicts': {result}"
        assert "count" in result, f"Missing 'count': {result}"
        assert isinstance(result["conflicts"], list)

    def test_d6_conflict_detected_same_hub(
            self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D6.3 — two active decisions sharing a hub_id are reported as a conflict."""
        hub_id = str(uuid.uuid4())
        FakeDecisionStore.seed(workspace_id=WS_A, title="Dec A", reason="r",
                               status="active", linked_hub_ids=[hub_id])
        FakeDecisionStore.seed(workspace_id=WS_A, title="Dec B", reason="r",
                               status="active", linked_hub_ids=[hub_id])
        result = mcp_tools.list_decision_conflicts(workspace_id=WS_A)
        assert result["count"] >= 1, (
            f"Expected at least 1 conflict for shared hub, got count={result['count']}"
        )

    def test_d6_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D6.4 — conflicts from WS_A are not visible from WS_B."""
        hub_id = str(uuid.uuid4())
        FakeDecisionStore.seed(workspace_id=WS_A, title="A Conflict 1", reason="r",
                               status="active", linked_hub_ids=[hub_id])
        FakeDecisionStore.seed(workspace_id=WS_A, title="A Conflict 2", reason="r",
                               status="active", linked_hub_ids=[hub_id])
        result_b = mcp_tools.list_decision_conflicts(workspace_id=WS_B)
        assert result_b["count"] == 0, (
            f"WS_B must not see WS_A conflicts; got count={result_b['count']}"
        )


# ---------------------------------------------------------------------------
# D7 — get_decision_timeline
# ---------------------------------------------------------------------------

class TestGetDecisionTimeline:
    def test_d7_callable(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D7.1 — get_decision_timeline is callable, returns without raw exception."""
        result = mcp_tools.get_decision_timeline(workspace_id=WS_A)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_d7_response_shape(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D7.2 — get_decision_timeline returns {active, superseded, reversed, draft, total}."""
        FakeDecisionStore.seed(workspace_id=WS_A, title="Active TL", reason="r",
                               status="active")
        FakeDecisionStore.seed(workspace_id=WS_A, title="Draft TL", reason="r",
                               status="draft")
        result = mcp_tools.get_decision_timeline(workspace_id=WS_A)
        for field in ("active", "superseded", "reversed", "draft", "total"):
            assert field in result, f"Missing field '{field}': {result}"
        assert isinstance(result["active"], list)
        assert isinstance(result["total"], int)

    def test_d7_ws_isolation(self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D7.3 — WS_A decisions not visible in WS_B timeline."""
        FakeDecisionStore.seed(workspace_id=WS_A, title="A Timeline Dec", reason="r",
                               status="active")
        result_b = mcp_tools.get_decision_timeline(workspace_id=WS_B)
        assert result_b["total"] == 0, (
            f"WS_B timeline must be empty; got total={result_b['total']}"
        )

    def test_d7_active_decisions_appear_in_active_bucket(
            self, hermetic_client_decisions: MCPHermeticClient) -> None:
        """D7.4 — active decisions appear in the 'active' bucket of the timeline."""
        FakeDecisionStore.seed(workspace_id=WS_A, title="Active Bucket", reason="r",
                               status="active")
        result = mcp_tools.get_decision_timeline(workspace_id=WS_A)
        titles = [d["title"] for d in result.get("active", [])]
        assert "Active Bucket" in titles, (
            f"Active decision not in active bucket; active titles={titles}"
        )
