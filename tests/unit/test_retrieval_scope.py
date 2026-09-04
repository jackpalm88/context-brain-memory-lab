"""Unit tests — first-class scoped retrieval (docs/DESIGN_SCOPED_RETRIEVAL.md).

Pure Python, no DB, no provider calls. Mirrors the mocking conventions of
tests/unit/test_retrieval_memory_type_filter.py (SQL/param capture via a fake
cursor) and tests/unit/test_m11c2_retrieval_envelope.py (FakeRetrievalAdapter +
TestClient for router-level threading).

Covers: RetrievalScope model validation, RetrievalRequest/AskRequest cross-field
validation against legacy memory_type(s), pre-scoring WHERE-clause construction
across all three candidate sources, hub-linked-path scope intersection, adapter
signature threading, router scope_applied provenance, MCP client/tool forwarding,
and /v1/ask audit requested_scope recording.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000003101"
SUBJECT = "00000000-0000-0000-0000-000000003102"
HUB_A = "00000000-0000-0000-0000-0000000000aa"
HUB_B = "00000000-0000-0000-0000-0000000000bb"


# ---------------------------------------------------------------------------
# 1. RetrievalScope model validation
# ---------------------------------------------------------------------------

class TestRetrievalScopeModel:
    def test_none_fields_valid(self):
        from memory_lab.api.services.retrieval_scope import RetrievalScope
        scope = RetrievalScope()
        assert scope.allowed_hubs is None
        assert scope.content_types is None

    def test_valid_allowed_hubs_and_content_types(self):
        from memory_lab.api.services.retrieval_scope import RetrievalScope
        scope = RetrievalScope(allowed_hubs=[HUB_A, HUB_B], content_types=["decision"])
        assert scope.allowed_hubs == [HUB_A, HUB_B]
        assert scope.content_types == ["decision"]

    def test_empty_allowed_hubs_rejected(self):
        from memory_lab.api.services.retrieval_scope import RetrievalScope
        with pytest.raises(ValidationError):
            RetrievalScope(allowed_hubs=[])

    def test_empty_content_types_rejected(self):
        from memory_lab.api.services.retrieval_scope import RetrievalScope
        with pytest.raises(ValidationError):
            RetrievalScope(content_types=[])

    def test_unknown_content_type_rejected(self):
        from memory_lab.api.services.retrieval_scope import RetrievalScope
        with pytest.raises(ValidationError) as exc_info:
            RetrievalScope(content_types=["not_a_real_type"])
        assert "Unknown retrieval_scope.content_types" in str(exc_info.value)

    def test_no_subject_scope_or_policy_scope_fields(self):
        # design doc §8: reserved names, not implemented — must not exist as accessors.
        from memory_lab.api.services.retrieval_scope import RetrievalScope
        fields = RetrievalScope.model_fields
        assert "subject_scope" not in fields
        assert "policy_scope" not in fields


# ---------------------------------------------------------------------------
# 2. RetrievalRequest — retrieval_scope vs legacy memory_type(s)
# ---------------------------------------------------------------------------

class TestRetrievalRequestScopeValidation:
    def _make(self, **kwargs):
        from memory_lab.api.routers.retrieval import RetrievalRequest
        return RetrievalRequest(query="test query", **kwargs)

    def test_no_scope_unchanged_behavior(self):
        req = self._make()
        assert req.retrieval_scope is None
        assert req.resolved_content_types() is None
        assert req.resolved_allowed_hubs() is None

    def test_scope_only_content_types(self):
        req = self._make(retrieval_scope={"content_types": ["decision", "evidence"]})
        assert req.resolved_content_types() == ["decision", "evidence"]

    def test_scope_only_allowed_hubs(self):
        req = self._make(retrieval_scope={"allowed_hubs": [HUB_A]})
        assert req.resolved_allowed_hubs() == [HUB_A]
        assert req.resolved_content_types() is None

    def test_scope_content_types_equivalent_to_legacy_memory_type_coexist(self):
        req = self._make(memory_type="decision", retrieval_scope={"content_types": ["decision"]})
        assert req.resolved_content_types() == ["decision"]

    def test_scope_content_types_equivalent_to_legacy_memory_types_coexist_any_order(self):
        req = self._make(
            memory_types=["decision", "evidence"],
            retrieval_scope={"content_types": ["evidence", "decision"]},
        )
        assert set(req.resolved_content_types()) == {"decision", "evidence"}

    def test_scope_content_types_conflicting_with_legacy_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make(memory_type="decision", retrieval_scope={"content_types": ["evidence"]})
        assert "conflicts" in str(exc_info.value)

    def test_scope_unknown_content_type_rejected_via_request(self):
        with pytest.raises(ValidationError):
            self._make(retrieval_scope={"content_types": ["bogus"]})

    def test_scope_empty_allowed_hubs_rejected_via_request(self):
        with pytest.raises(ValidationError):
            self._make(retrieval_scope={"allowed_hubs": []})


# ---------------------------------------------------------------------------
# 3. AskRequest — mirrors RetrievalRequest scope validation
# ---------------------------------------------------------------------------

class TestAskRequestScopeValidation:
    def test_no_scope_unchanged_behavior(self):
        from memory_lab.reasoning.models import AskRequest
        req = AskRequest(query="x")
        assert req.retrieval_scope is None
        assert req.resolved_content_types() is None
        assert req.resolved_allowed_hubs() is None

    def test_scope_allowed_hubs_resolved(self):
        from memory_lab.reasoning.models import AskRequest
        req = AskRequest(query="x", retrieval_scope={"allowed_hubs": [HUB_A]})
        assert req.resolved_allowed_hubs() == [HUB_A]

    def test_scope_content_types_conflicting_with_legacy_rejected(self):
        from memory_lab.reasoning.models import AskRequest
        with pytest.raises(ValidationError):
            AskRequest(query="x", memory_type="decision", retrieval_scope={"content_types": ["evidence"]})

    def test_scope_content_types_equivalent_with_legacy_coexist(self):
        from memory_lab.reasoning.models import AskRequest
        req = AskRequest(query="x", memory_type="decision", retrieval_scope={"content_types": ["decision"]})
        assert req.resolved_content_types() == ["decision"]


# ---------------------------------------------------------------------------
# 4. SQL/param construction — allowed_hubs pre-scoring WHERE clause
# ---------------------------------------------------------------------------

def _fake_conn(captured_sql: list, captured_params: list):
    def _make():
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall.return_value = []

        def capture_execute(sql, params=None):
            captured_sql.append(sql)
            if params:
                captured_params.extend(params)
        cur.execute = capture_execute
        conn.cursor.return_value = cur
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn
    return _make


class TestSqlParamInjectionAllowedHubs:
    def _adapter(self):
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        return RetrievalAdapter("postgresql://fake/fake")

    def test_deterministic_search_no_allowed_hubs_no_extra_clause(self):
        adapter = self._adapter()
        sql, params = [], []
        with patch.object(adapter, "_conn", side_effect=_fake_conn(sql, params)):
            adapter._deterministic_vector_search("some text", workspace_id="ws-1")
        assert "cb_hub_content" not in sql[0]
        assert [HUB_A] not in [p for p in params if isinstance(p, list)]

    def test_deterministic_search_allowed_hubs_adds_subquery_and_param(self):
        adapter = self._adapter()
        sql, params = [], []
        with patch.object(adapter, "_conn", side_effect=_fake_conn(sql, params)):
            adapter._deterministic_vector_search("some text", workspace_id="ws-1", allowed_hubs=[HUB_A, HUB_B])
        assert "cb_hub_content" in sql[0]
        assert "ANY(SELECT content_id FROM cb_hub_content WHERE hub_id = ANY" in sql[0]
        assert [HUB_A, HUB_B] in params

    def test_pgvector_search_allowed_hubs_adds_subquery_and_param(self):
        adapter = self._adapter()
        sql, params = [], []
        with patch.object(adapter, "_conn", side_effect=_fake_conn(sql, params)):
            adapter._pgvector_knn_search("some text", [0.1, 0.2], workspace_id="ws-1", allowed_hubs=[HUB_A])
        assert "cb_hub_content" in sql[0]
        assert [HUB_A] in params

    def test_pgvector_search_no_allowed_hubs_unchanged(self):
        adapter = self._adapter()
        sql, params = [], []
        with patch.object(adapter, "_conn", side_effect=_fake_conn(sql, params)):
            adapter._pgvector_knn_search("some text", [0.1, 0.2], workspace_id="ws-1")
        assert "cb_hub_content" not in sql[0]

    def test_allowed_hubs_combines_with_memory_types_via_and(self):
        adapter = self._adapter()
        sql, params = [], []
        with patch.object(adapter, "_conn", side_effect=_fake_conn(sql, params)):
            adapter._deterministic_vector_search(
                "some text", workspace_id="ws-1", memory_types=["decision"], allowed_hubs=[HUB_A]
            )
        assert ["decision"] in params
        assert [HUB_A] in params
        # both filters present in the same WHERE (joined by AND), workspace isolation preserved
        assert "c.workspace_id = %s::uuid" in sql[0]
        assert "c.memory_type = ANY" in sql[0]
        assert "cb_hub_content" in sql[0]


# ---------------------------------------------------------------------------
# 5. _hub_linked_results — scope intersection (design doc §6.1)
# ---------------------------------------------------------------------------

class TestHubLinkedResultsScopeIntersection:
    def _adapter(self):
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        return RetrievalAdapter("postgresql://fake/fake")

    def test_matched_hub_outside_allowed_hubs_yields_zero_without_content_lookup(self):
        adapter = self._adapter()
        adapter.hub_store.match_query = MagicMock(return_value={"hub_id": HUB_B, "title": "Other"})
        adapter.hub_store.get_hub_content_ids = MagicMock(return_value=["content-1"])

        results = adapter._hub_linked_results("query text", workspace_id="ws-1", allowed_hubs=[HUB_A])

        assert results == []
        adapter.hub_store.get_hub_content_ids.assert_not_called()

    def test_matched_hub_inside_allowed_hubs_proceeds(self):
        adapter = self._adapter()
        adapter.hub_store.match_query = MagicMock(return_value={"hub_id": HUB_A, "title": "Match", "aliases": [], "related_terms": []})
        adapter.hub_store.get_hub_content_ids = MagicMock(return_value=[])

        results = adapter._hub_linked_results("query text", workspace_id="ws-1", allowed_hubs=[HUB_A])

        adapter.hub_store.get_hub_content_ids.assert_called_once()
        assert results == []  # no content ids -> empty, but the gate did not short-circuit

    def test_matched_hub_case_insensitive_membership(self):
        adapter = self._adapter()
        adapter.hub_store.match_query = MagicMock(return_value={"hub_id": HUB_A.upper(), "title": "Match", "aliases": [], "related_terms": []})
        adapter.hub_store.get_hub_content_ids = MagicMock(return_value=[])

        adapter._hub_linked_results("query text", workspace_id="ws-1", allowed_hubs=[HUB_A])

        adapter.hub_store.get_hub_content_ids.assert_called_once()

    def test_no_allowed_hubs_unaffected_backward_compat(self):
        adapter = self._adapter()
        adapter.hub_store.match_query = MagicMock(return_value={"hub_id": HUB_B, "title": "Any", "aliases": [], "related_terms": []})
        adapter.hub_store.get_hub_content_ids = MagicMock(return_value=[])

        adapter._hub_linked_results("query text", workspace_id="ws-1")

        adapter.hub_store.get_hub_content_ids.assert_called_once()


# ---------------------------------------------------------------------------
# 6. RetrievalAdapter.search() threads allowed_hubs into all three sources
# ---------------------------------------------------------------------------

class TestSearchThreadsAllowedHubs:
    def test_search_signature_accepts_allowed_hubs_defaulting_none(self):
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        import inspect
        sig = inspect.signature(RetrievalAdapter.search)
        assert "allowed_hubs" in sig.parameters
        assert sig.parameters["allowed_hubs"].default is None

    def test_search_forwards_allowed_hubs_to_deterministic_and_hub_paths(self, monkeypatch):
        import memory_lab.api.services.retrieval_adapter as retrieval_module
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter("postgresql://fake/fake")

        class FakeSearchAdapter:
            def search(self, **kwargs):
                # exercises the deterministic vector_search_fn passed in, as production does
                return kwargs["vector_search_fn"](kwargs["query"])

        adapter.adapter = FakeSearchAdapter()
        det_calls = []
        hub_calls = []
        monkeypatch.setattr(
            adapter,
            "_deterministic_vector_search",
            lambda query, workspace_id=None, memory_types=None, allowed_hubs=None: det_calls.append(allowed_hubs) or [],
        )
        monkeypatch.setattr(
            adapter,
            "_hub_linked_results",
            lambda query, workspace_id=None, memory_types=None, allowed_hubs=None: hub_calls.append(allowed_hubs) or [],
        )
        monkeypatch.setattr(retrieval_module, "rank_by_composite", lambda rows, query: rows)
        monkeypatch.setattr(retrieval_module, "build_ranking_signals", lambda rows: {})

        adapter.search("q", workspace_id="ws-1", allowed_hubs=[HUB_A])

        assert det_calls and det_calls[0] == [HUB_A]
        assert hub_calls and hub_calls[0] == [HUB_A]

    def test_search_default_allowed_hubs_none_is_byte_identical_call_shape(self, monkeypatch):
        """Non-opted callers (no allowed_hubs) must pass None through unchanged — checklist point 4."""
        import memory_lab.api.services.retrieval_adapter as retrieval_module
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

        adapter = RetrievalAdapter("postgresql://fake/fake")

        class FakeSearchAdapter:
            def search(self, **kwargs):
                return kwargs["vector_search_fn"](kwargs["query"])

        adapter.adapter = FakeSearchAdapter()
        det_calls = []
        monkeypatch.setattr(
            adapter,
            "_deterministic_vector_search",
            lambda query, workspace_id=None, memory_types=None, allowed_hubs=None: det_calls.append(allowed_hubs) or [],
        )
        monkeypatch.setattr(adapter, "_hub_linked_results", lambda *a, **kw: [])
        monkeypatch.setattr(retrieval_module, "rank_by_composite", lambda rows, query: rows)
        monkeypatch.setattr(retrieval_module, "build_ranking_signals", lambda rows: {})

        adapter.search("q", workspace_id="ws-1")

        assert det_calls == [None]


# ---------------------------------------------------------------------------
# 7. Router — scope_applied provenance + threading (FakeRetrievalAdapter + TestClient)
# ---------------------------------------------------------------------------

class FakeRetrievalAdapter:
    calls: list = []

    def __init__(self, database_url: str):
        self.database_url = database_url

    def search(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return []


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.dependencies.auth import require_permission
    from memory_lab.api.main import create_app
    import memory_lab.api.routers.retrieval as retrieval_router

    FakeRetrievalAdapter.calls = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/example")
    monkeypatch.setattr(retrieval_router, "RetrievalAdapter", FakeRetrievalAdapter)

    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id=SUBJECT,
            subject_type="user",
            workspace_id=WS,
            role="owner",
            auth_method="test",
        )

    app.dependency_overrides[require_permission("retrieval.search")] = override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                closure_values = [cell.cell_contents for cell in call.__closure__]
                if "retrieval.search" in closure_values:
                    app.dependency_overrides[call] = override
    return TestClient(app)


class TestRouterScopeApplied:
    def test_no_scope_omits_scope_applied_and_passes_none(self, monkeypatch):
        r = _client(monkeypatch).post("/v1/retrieval/search", json={"query": "alpha"})
        assert r.status_code == 200, r.text
        assert "scope_applied" not in r.json()
        assert FakeRetrievalAdapter.calls[-1]["allowed_hubs"] is None

    def test_scope_supplied_returns_scope_applied_and_forwards_allowed_hubs(self, monkeypatch):
        r = _client(monkeypatch).post(
            "/v1/retrieval/search",
            json={"query": "alpha", "retrieval_scope": {"allowed_hubs": [HUB_A], "content_types": ["decision"]}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scope_applied"] == {
            "allowed_hubs": [HUB_A],
            "content_types": ["decision"],
            "enforcement": "pre_filter",
        }
        assert FakeRetrievalAdapter.calls[-1]["allowed_hubs"] == [HUB_A]
        assert FakeRetrievalAdapter.calls[-1]["memory_types"] == ["decision"]

    def test_conflicting_scope_and_legacy_memory_type_rejected(self, monkeypatch):
        r = _client(monkeypatch).post(
            "/v1/retrieval/search",
            json={
                "query": "alpha",
                "memory_type": "decision",
                "retrieval_scope": {"content_types": ["evidence"]},
            },
        )
        assert r.status_code == 422

    def test_nonexistent_hub_scope_still_returns_200_zero_results_no_fallback(self, monkeypatch):
        # Fail-closed at the SQL layer means the adapter simply returns whatever it
        # returns (FakeRetrievalAdapter returns [] regardless) — the router must not
        # special-case an "empty scope result" into re-querying unscoped.
        r = _client(monkeypatch).post(
            "/v1/retrieval/search",
            json={"query": "alpha", "retrieval_scope": {"allowed_hubs": [HUB_A]}},
        )
        assert r.status_code == 200
        assert r.json()["results"] == []
        assert len(FakeRetrievalAdapter.calls) == 1  # exactly one search() call — no retry/fallback


# ---------------------------------------------------------------------------
# 8. MCP client / tool forwarding
# ---------------------------------------------------------------------------

class TestMcpForwarding:
    def test_retrieval_search_client_forwards_retrieval_scope(self):
        from tests.unit.test_m7_mcp_expose_only import RecordingClient

        client = RecordingClient()
        call = client.retrieval_search(
            "alpha envelope",
            retrieval_scope={"allowed_hubs": [HUB_A]},
            workspace_id=WS,
        )
        assert call["json_body"]["retrieval_scope"] == {"allowed_hubs": [HUB_A]}

    def test_retrieval_search_client_omits_retrieval_scope_when_not_supplied(self):
        from tests.unit.test_m7_mcp_expose_only import RecordingClient

        client = RecordingClient()
        call = client.retrieval_search("alpha envelope", workspace_id=WS)
        assert "retrieval_scope" not in call["json_body"]

    def test_ask_client_forwards_retrieval_scope(self):
        from tests.unit.test_m7_mcp_expose_only import RecordingClient

        client = RecordingClient()
        call = client.ask("q", retrieval_scope={"content_types": ["decision"]}, workspace_id=WS)
        assert call["json_body"]["retrieval_scope"] == {"content_types": ["decision"]}

    def test_memory_lab_retrieval_search_tool_forwards_retrieval_scope(self):
        import memory_lab.mcp.tools as tools_module

        captured = {}

        class FakeClient:
            def retrieval_search(self, **kwargs):
                captured.update(kwargs)
                return {"results": [], "count": 0}

        with patch.object(tools_module, "_client", return_value=FakeClient()):
            tools_module.memory_lab_retrieval_search("q", retrieval_scope={"allowed_hubs": [HUB_A]})

        assert captured["retrieval_scope"] == {"allowed_hubs": [HUB_A]}

    def test_query_memory_tool_forwards_retrieval_scope(self):
        import memory_lab.mcp.tools as tools_module

        captured = {}

        class FakeClient:
            def ask(self, **kwargs):
                captured.update(kwargs)
                return {"answer": "", "citations": [], "status": "ok", "confidence": 0.0}

        with patch.object(tools_module, "_client", return_value=FakeClient()):
            tools_module.query_memory("q", retrieval_scope={"allowed_hubs": [HUB_A]})

        assert captured["retrieval_scope"] == {"allowed_hubs": [HUB_A]}

    def test_query_memory_tool_omits_retrieval_scope_when_not_supplied(self):
        import memory_lab.mcp.tools as tools_module

        captured = {}

        class FakeClient:
            def ask(self, **kwargs):
                captured.update(kwargs)
                return {"answer": "", "citations": [], "status": "ok", "confidence": 0.0}

        with patch.object(tools_module, "_client", return_value=FakeClient()):
            tools_module.query_memory("q")

        assert "retrieval_scope" not in captured


# ---------------------------------------------------------------------------
# 9. /v1/ask audit — requested_scope + scope_enforcement
# ---------------------------------------------------------------------------

class TestAskAuditRequestedScope:
    def _make_mock_conn(self):
        cur = MagicMock()
        conn = MagicMock()
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cur

    def test_requested_scope_recorded_in_metadata(self):
        import json
        from memory_lab.query.ask_audit import record_ask_event

        conn, cur = self._make_mock_conn()
        scope = {"allowed_hubs": [HUB_A], "content_types": None}
        with patch("memory_lab.query.ask_audit.psycopg2.connect", return_value=conn):
            record_ask_event(
                database_url="postgresql://unit:x@localhost/testdb",
                workspace_id="ws-001",
                latency_ms=10,
                retrieval_path="pgvector",
                result_status="ok",
                result_mode="deterministic",
                evidence_count=1,
                degraded=False,
                degraded_reason=None,
                provider_used=False,
                requested_scope=scope,
            )
        _, params = cur.execute.call_args[0]
        metadata = json.loads(params[2])
        assert metadata["requested_scope"] == scope
        assert metadata["scope_enforcement"] == "pre_filter"

    def test_requested_scope_defaults_to_null(self):
        import json
        from memory_lab.query.ask_audit import record_ask_event

        conn, cur = self._make_mock_conn()
        with patch("memory_lab.query.ask_audit.psycopg2.connect", return_value=conn):
            record_ask_event(
                database_url="postgresql://unit:x@localhost/testdb",
                workspace_id="ws-001",
                latency_ms=10,
                retrieval_path="pgvector",
                result_status="ok",
                result_mode="deterministic",
                evidence_count=1,
                degraded=False,
                degraded_reason=None,
                provider_used=False,
            )
        _, params = cur.execute.call_args[0]
        metadata = json.loads(params[2])
        assert metadata["requested_scope"] is None
        assert metadata["scope_enforcement"] == "pre_filter"

    def test_query_service_execute_passes_requested_scope(self):
        from types import SimpleNamespace
        from memory_lab.reasoning.models import AskRequest, AskResponse

        fake_response = AskResponse(
            answer="test",
            intent="general",
            confidence=0.9,
            confidence_explanation="test",
            status="ok",
            mode="deterministic",
            evidence=[],
            degraded=False,
            workspace_id="ws-001",
        )
        fake_adapter = SimpleNamespace(
            database_url="postgresql://unit:x@localhost/testdb",
            last_debug_metadata={"stage_metrics": {"pgvector": {"used": False, "output_count": 0}}},
            search=lambda **kw: [],
        )

        from memory_lab.query import service as svc_module

        with patch.object(svc_module, "detect_intent", return_value=SimpleNamespace(intent="general")), \
             patch.object(svc_module, "policy_for_intent", return_value=SimpleNamespace(top_k=5, snippet_char_limit=500)), \
             patch.object(svc_module, "normalize_evidence", return_value=[]), \
             patch.object(svc_module, "build_support_only_context_pack_for_ask", return_value=SimpleNamespace()), \
             patch.object(svc_module, "evidence_items_from_supporting_context_pack", return_value=[]), \
             patch.object(svc_module, "synthesize_answer", return_value=fake_response), \
             patch.object(svc_module, "apply_provider_answer", return_value=fake_response), \
             patch.object(svc_module, "record_ask_event") as mock_record:

            from memory_lab.query.service import QueryService
            qs = QueryService(retrieval_adapter=fake_adapter)
            req = AskRequest(query="test", retrieval_scope={"allowed_hubs": [HUB_A]})
            qs.execute(req, workspace_id="ws-001")

        kwargs = mock_record.call_args.kwargs
        assert kwargs["requested_scope"] == {"allowed_hubs": [HUB_A], "content_types": None}

    def test_query_service_execute_passes_allowed_hubs_and_content_types_to_adapter(self):
        from types import SimpleNamespace
        from memory_lab.reasoning.models import AskRequest, AskResponse

        fake_response = AskResponse(
            answer="test", intent="general", confidence=0.9, confidence_explanation="test",
            status="ok", mode="deterministic", evidence=[], degraded=False, workspace_id="ws-001",
        )
        search_calls = []
        fake_adapter = SimpleNamespace(
            database_url="postgresql://unit:x@localhost/testdb",
            last_debug_metadata={"stage_metrics": {}},
            search=lambda **kw: search_calls.append(kw) or [],
        )

        from memory_lab.query import service as svc_module

        with patch.object(svc_module, "detect_intent", return_value=SimpleNamespace(intent="general")), \
             patch.object(svc_module, "policy_for_intent", return_value=SimpleNamespace(top_k=5, snippet_char_limit=500)), \
             patch.object(svc_module, "normalize_evidence", return_value=[]), \
             patch.object(svc_module, "build_support_only_context_pack_for_ask", return_value=SimpleNamespace()), \
             patch.object(svc_module, "evidence_items_from_supporting_context_pack", return_value=[]), \
             patch.object(svc_module, "synthesize_answer", return_value=fake_response), \
             patch.object(svc_module, "apply_provider_answer", return_value=fake_response), \
             patch.object(svc_module, "record_ask_event"):

            from memory_lab.query.service import QueryService
            qs = QueryService(retrieval_adapter=fake_adapter)
            req = AskRequest(query="test", retrieval_scope={"allowed_hubs": [HUB_A], "content_types": ["decision"]})
            qs.execute(req, workspace_id="ws-001")

        assert search_calls[0]["allowed_hubs"] == [HUB_A]
        assert search_calls[0]["memory_types"] == ["decision"]


# ---------------------------------------------------------------------------
# 10. No workspace-wide-then-filter shortcut (structural guard)
# ---------------------------------------------------------------------------

class TestNoPostHocFiltering:
    def test_deterministic_search_hub_filter_is_sql_not_python(self):
        """Guards against a regression that fetches workspace-wide rows and filters
        in Python — the hub restriction must live in the WHERE clause itself."""
        import inspect
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        src = inspect.getsource(RetrievalAdapter._deterministic_vector_search)
        assert "cb_hub_content" in src
        # the hub filter must be part of the SQL string built into where_parts,
        # not a post-fetch list comprehension over `rows`/`results`.
        assert "if allowed_hubs" in src

    def test_pgvector_search_hub_filter_is_sql_not_python(self):
        import inspect
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        src = inspect.getsource(RetrievalAdapter._pgvector_knn_search)
        assert "cb_hub_content" in src
        assert "if allowed_hubs" in src
