"""tests/unit/test_dx3_observability.py

DX-3 — Ask Metrics + Keyword Audit hermetic tests.

No live DB, no live embedding provider, no secrets.

Coverage:
  Part A — ask_audit module (10 tests)
    A-1  derive_retrieval_path: zero evidence → no_context
    A-2  derive_retrieval_path: pgvector used → pgvector
    A-3  derive_retrieval_path: graph used, evidence > 0 → graph_rescue_nonzero
    A-4  derive_retrieval_path: graph used, evidence = 0 → graph_rescue_zero (redundant with no_context)
    A-5  derive_retrieval_path: only deterministic → deterministic
    A-6  derive_retrieval_path: None stage_metrics → deterministic
    A-7  record_ask_event: happy-path inserts correct row
    A-8  record_ask_event: DB error is swallowed (no raise)
    A-9  record_ask_event: reason_code == retrieval_path
    A-10 QueryService.execute() calls record_ask_event with correct args

  Part B — keyword audit (8 tests)
    B-1  _count_keywords: returns correct counts
    B-2  _count_keywords: stop-words excluded
    B-3  _count_keywords: short tokens (< 3 chars) excluded
    B-4  _count_keywords: empty input → empty counter
    B-5  _count_keywords: deterministic order (same input → same output)
    B-6  get_keywords endpoint: 200 + correct shape
    B-7  get_keywords endpoint: workspace isolation (only caller's workspace)
    B-8  get_keywords endpoint: limit respected
"""
from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ============================================================
# Shared auth-bypass fixture (same pattern as test_dx2)
# ============================================================

import memory_lab.api.dependencies.auth as _auth_mod
import memory_lab.api.workspace_context as _ws_mod
from memory_lab.api.workspace_context import WorkspaceContext

_WS_ID = "00000000-0000-0000-0000-000000000099"
_FAKE_WORKSPACE = WorkspaceContext(
    workspace_id=_WS_ID,
    source="db_default",
    is_default=True,
    local_dev_default_used=False,
    slug="unit-test",
)
_MOCK_AUTH = SimpleNamespace(
    workspace_id=_WS_ID,
    permissions=["retrieval.search"],
    subject_id=None,
    role="admin",
)


def _patch_auth(monkeypatch):
    monkeypatch.setattr(_ws_mod, "resolve_workspace_context", lambda *a, **kw: _FAKE_WORKSPACE)
    monkeypatch.setattr(_auth_mod, "resolve_workspace_context", lambda *a, **kw: _FAKE_WORKSPACE)
    monkeypatch.setattr(_auth_mod, "resolve_auth_context", lambda perm, ws, authz: _MOCK_AUTH)


# ============================================================
# Imports under test
# ============================================================

from memory_lab.query.ask_audit import derive_retrieval_path, record_ask_event
from memory_lab.query.ask_audit import (
    _PATH_PGVECTOR,
    _PATH_DETERMINISTIC,
    _PATH_GRAPH_RESCUE_NONZERO,
    _PATH_GRAPH_RESCUE_ZERO,
    _PATH_NO_CONTEXT,
)
from memory_lab.api.routers.audit_keywords import _count_keywords


# ============================================================
# Part A — ask_audit module
# ============================================================

class TestDeriveRetrievalPath:
    """A-1 … A-6"""

    def test_a1_zero_evidence_is_no_context(self):
        metrics = {"pgvector": {"used": True, "output_count": 5}}
        assert derive_retrieval_path(metrics, 0) == _PATH_NO_CONTEXT

    def test_a2_pgvector_used(self):
        metrics = {
            "pgvector": {"used": True, "output_count": 3},
            "graph_expansion": {"used": False},
        }
        assert derive_retrieval_path(metrics, 3) == _PATH_PGVECTOR

    def test_a3_graph_rescue_nonzero(self):
        metrics = {
            "pgvector": {"used": False, "output_count": 0},
            "graph_expansion": {"used": True},
        }
        assert derive_retrieval_path(metrics, 2) == _PATH_GRAPH_RESCUE_NONZERO

    def test_a4_graph_rescue_zero_evidence(self):
        # graph was used but evidence_count is 0 → overridden by no_context (priority 1)
        metrics = {
            "pgvector": {"used": False, "output_count": 0},
            "graph_expansion": {"used": True},
        }
        assert derive_retrieval_path(metrics, 0) == _PATH_NO_CONTEXT

    def test_a5_deterministic_only(self):
        metrics = {
            "pgvector": {"used": False, "output_count": 0},
            "graph_expansion": {"used": False},
        }
        assert derive_retrieval_path(metrics, 4) == _PATH_DETERMINISTIC

    def test_a6_none_stage_metrics(self):
        assert derive_retrieval_path(None, 2) == _PATH_DETERMINISTIC


class TestRecordAskEvent:
    """A-7 … A-9"""

    _COMMON_KWARGS = dict(
        database_url="postgresql://unit:x@localhost/testdb",
        workspace_id="ws-001",
        latency_ms=42,
        retrieval_path="pgvector",
        result_status="ok",
        result_mode="deterministic",
        evidence_count=3,
        degraded=False,
        degraded_reason=None,
        provider_used=False,
    )

    def _make_mock_conn(self):
        cur = MagicMock()
        conn = MagicMock()
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cur

    def test_a7_happy_path_inserts_row(self):
        conn, cur = self._make_mock_conn()
        with patch("memory_lab.query.ask_audit.psycopg2.connect", return_value=conn):
            record_ask_event(**self._COMMON_KWARGS)
        cur.execute.assert_called_once()
        sql, params = cur.execute.call_args[0]
        assert "cb_audit_events" in sql
        assert "'ask'" in sql           # event_type literal in SQL
        assert params[0] == "ws-001"   # workspace_id
        assert params[1] == "pgvector" # retrieval_path → reason_code

    def test_a8_db_error_swallowed(self):
        with patch("memory_lab.query.ask_audit.psycopg2.connect", side_effect=Exception("boom")):
            # Must not raise
            record_ask_event(**self._COMMON_KWARGS)

    def test_a9_reason_code_equals_retrieval_path(self):
        conn, cur = self._make_mock_conn()
        with patch("memory_lab.query.ask_audit.psycopg2.connect", return_value=conn):
            record_ask_event(**{**self._COMMON_KWARGS, "retrieval_path": "graph_rescue_nonzero"})
        _, params = cur.execute.call_args[0]
        # params: (workspace_id, reason_code, metadata_json)
        assert params[1] == "graph_rescue_nonzero"  # reason_code == retrieval_path


class TestQueryServiceAuditIntegration:
    """A-10 — QueryService.execute() triggers record_ask_event with correct args."""

    def test_a10_execute_calls_record_ask_event(self):
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
            qs.execute(AskRequest(query="test"), workspace_id="ws-001")

        mock_record.assert_called_once()
        kwargs = mock_record.call_args.kwargs
        assert kwargs["workspace_id"] == "ws-001"
        assert kwargs["result_status"] == "ok"
        assert kwargs["evidence_count"] == 0
        # zero evidence → no_context takes priority over any stage metric path
        assert kwargs["retrieval_path"] == _PATH_NO_CONTEXT
        assert isinstance(kwargs["latency_ms"], int)


# ============================================================
# Part B — keyword audit
# ============================================================

class TestCountKeywords:
    """B-1 … B-5"""

    def test_b1_correct_counts(self):
        chunks = ["memory context memory retrieval context context"]
        result = _count_keywords(chunks)
        assert result["memory"] == 2
        assert result["context"] == 3
        assert result["retrieval"] == 1

    def test_b2_stop_words_excluded(self):
        chunks = ["the and context for retrieval"]
        result = _count_keywords(chunks)
        assert "the" not in result
        assert "and" not in result
        assert "for" not in result
        assert "context" in result

    def test_b3_short_tokens_excluded(self):
        chunks = ["an of is context"]
        result = _count_keywords(chunks)
        assert "an" not in result
        assert "of" not in result
        assert "is" not in result

    def test_b4_empty_input(self):
        assert _count_keywords([]) == Counter()

    def test_b5_deterministic_order(self):
        chunks = ["context memory retrieval context memory context"]
        r1 = _count_keywords(chunks)
        r2 = _count_keywords(chunks)
        top1 = sorted(r1.items(), key=lambda kv: (-kv[1], kv[0]))
        top2 = sorted(r2.items(), key=lambda kv: (-kv[1], kv[0]))
        assert top1 == top2


class TestKeywordsEndpoint:
    """B-6 … B-8"""

    _FAKE_SETTINGS = SimpleNamespace(
        database_url="postgresql://unit:x@localhost/testdb",
        ask_provider_synthesis_enabled=False,
    )

    def _make_app(self, monkeypatch, mock_chunks: List[str]):
        _patch_auth(monkeypatch)
        import memory_lab.api.routers.audit_keywords as kw_mod
        monkeypatch.setattr(kw_mod, "get_settings", lambda: self._FAKE_SETTINGS)
        monkeypatch.setattr(kw_mod, "_fetch_chunks", lambda db, ws: mock_chunks)
        from memory_lab.api.routers.audit_keywords import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_b6_200_correct_shape(self, monkeypatch):
        chunks = ["context memory retrieval context context memory"]
        client = TestClient(self._make_app(monkeypatch, chunks))
        resp = client.get("/v1/audit/keywords")
        assert resp.status_code == 200
        data = resp.json()
        assert "keywords" in data
        assert "total_chunks_scanned" in data
        assert data["total_chunks_scanned"] == 1
        assert data["workspace_id"] == _WS_ID
        kws = [e["keyword"] for e in data["keywords"]]
        assert "context" in kws

    def test_b7_workspace_isolation(self, monkeypatch):
        """_fetch_chunks receives the auth workspace_id, not a hardcoded one."""
        captured = {}
        import memory_lab.api.routers.audit_keywords as kw_mod
        _patch_auth(monkeypatch)
        monkeypatch.setattr(kw_mod, "get_settings", lambda: self._FAKE_SETTINGS)

        def _spy_fetch(db, ws):
            captured["ws"] = ws
            return ["context memory retrieval"]

        monkeypatch.setattr(kw_mod, "_fetch_chunks", _spy_fetch)
        from memory_lab.api.routers.audit_keywords import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        client.get("/v1/audit/keywords")
        assert captured["ws"] == _WS_ID

    def test_b8_limit_respected(self, monkeypatch):
        # Use distinct alpha-only words so tokeniser doesn't collapse them
        distinct_words = [
            "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
            "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
            "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
            "xray", "yankee", "zulu", "able", "baker", "cast", "dog", "easy",
            "fox", "george", "how", "item", "jig", "king", "love", "mike", "nan",
            "oboe", "peter", "queen", "roger", "sugar", "tare", "uncle", "victor",
            "william", "xerxes",
        ]
        chunks = [" ".join(distinct_words)]
        client = TestClient(self._make_app(monkeypatch, chunks))
        resp = client.get("/v1/audit/keywords?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()["keywords"]) == 3
