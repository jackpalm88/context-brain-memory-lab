"""M11C-2-1 raw retrieval input/envelope parity tests.

Focused, provider-free, DB-free tests for the public retrieval container only.
No ranking rewrite, graph diagnostics, score_components, or full search_raw_chunks
parity is asserted here.
"""
from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000002101"
SUBJECT = "00000000-0000-0000-0000-000000002102"


class FakeRetrievalAdapter:
    calls: list[dict[str, Any]] = []

    def __init__(self, database_url: str):
        self.database_url = database_url

    def search(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return [
            {
                "content_id": "m11c21-1",
                "chunk_id": "chunk-1",
                "text": "alpha raw retrieval envelope one",
                "score": 0.91,
                "retrieval_path": "content_chunk_workspace_scoped",
            },
            {
                "content_id": "m11c21-2",
                "chunk_id": "chunk-2",
                "text": "alpha raw retrieval envelope two",
                "score": 0.82,
                "retrieval_path": "content_chunk_workspace_scoped",
            },
        ]


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


def test_retrieval_request_accepts_m11c21_inputs():
    from memory_lab.api.routers.retrieval import RetrievalRequest

    req = RetrievalRequest(
        query="alpha envelope",
        limit=7,
        debug=True,
        only_clean=False,
        memory_types=["decision", "evidence"],
    )

    assert req.limit == 7
    assert req.debug is True
    assert req.only_clean is False
    assert req.resolved_memory_types() == ["decision", "evidence"]


def test_retrieval_search_honors_limit_and_returns_structured_envelope(monkeypatch):
    r = _client(monkeypatch).post(
        "/v1/retrieval/search",
        json={"query": "alpha envelope", "limit": 1, "only_clean": True},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "alpha envelope"
    assert body["limit"] == 1
    assert body["only_clean"] is True
    assert len(body["results"]) == 1
    assert body["count"] == 1  # backwards-compatible count
    assert body["result_count"] == 1
    assert body["mode"] == "workspace_scoped_deterministic_db"
    assert body["source"] == "retrieval_adapter"
    assert body["status"] == "ok"
    assert body["degraded"] is False
    assert body["workspace_id"] == WS
    assert "debug_metadata" not in body


def test_retrieval_search_debug_true_returns_safe_debug_metadata(monkeypatch):
    r = _client(monkeypatch).post(
        "/v1/retrieval/search",
        json={"query": "alpha envelope", "debug": True, "only_clean": True},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    debug = body["debug_metadata"]
    assert body["debug"] is True
    assert debug["requested"] is True
    assert debug["stage_metrics"]["adapter_search"]["attempted"] is True
    assert debug["stage_metrics"]["normalize"]["output_count"] == body["result_count"]
    assert debug["filters_applied"]["only_clean"]["requested"] is True
    assert debug["filters_applied"]["only_clean"]["status"] == "accepted_noop"
    assert "postgresql://" not in str(debug)


def test_retrieval_search_passes_existing_memory_type_filter(monkeypatch):
    r = _client(monkeypatch).post(
        "/v1/retrieval/search",
        json={"query": "alpha envelope", "memory_type": "decision"},
    )

    assert r.status_code == 200, r.text
    assert FakeRetrievalAdapter.calls[-1]["memory_types"] == ["decision"]


def test_mcp_retrieval_client_forwards_m11c21_inputs():
    from tests.unit.test_m7_mcp_expose_only import RecordingClient

    client = RecordingClient()
    call = client.retrieval_search(
        "alpha envelope",
        limit=3,
        debug=True,
        only_clean=False,
        workspace_id=WS,
    )

    assert call["path"] == "/v1/retrieval/search"
    assert call["workspace_id"] == WS
    assert call["json_body"] == {
        "query": "alpha envelope",
        "limit": 3,
        "debug": True,
        "only_clean": False,
    }
