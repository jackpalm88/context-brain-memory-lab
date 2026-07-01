"""M11C-2-3 debug stage metrics tests.

Focused, provider-free, DB-free tests. These tests assert observability only:
metrics describe the existing retrieval flow and must not change ranking, scoring,
or retrieval behavior.
"""
from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000002301"
SUBJECT = "00000000-0000-0000-0000-000000002302"


class FakeStageMetricsAdapter:
    calls: list[dict[str, Any]] = []
    instances: list["FakeStageMetricsAdapter"] = []

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.last_debug_metadata = {}
        self.__class__.instances.append(self)

    def search(self, **kwargs):
        self.__class__.calls.append(kwargs)
        self.last_debug_metadata = {
            "stage_metrics": {
                "adapter_search": {
                    "attempted": True,
                    "status": "ok",
                    "candidate_count": 4,
                    "output_count": 4,
                    "duration_ms": 3.25,
                },
                "deterministic_retrieval": {
                    "attempted": True,
                    "used": True,
                    "skipped": False,
                    "output_count": 2,
                    "reason": None,
                },
                "pgvector": {
                    "attempted": True,
                    "used": False,
                    "skipped": True,
                    "output_count": 0,
                    "reason": "provider_disabled",
                },
                "hub_inclusion": {
                    "attempted": True,
                    "used": True,
                    "skipped": False,
                    "candidate_count": 1,
                    "output_count": 1,
                    "reason": None,
                },
                "graph_expansion": {
                    "attempted": True,
                    "used": False,
                    "skipped": True,
                    "expanded_query_count": 0,
                    "reason": "no_expanded_terms",
                },
            },
            "degraded_reasons": ["provider_disabled"],
        }
        return [
            {
                "content_id": "m11c23-a",
                "chunk_id": "chunk-a",
                "text": "alpha debug metrics deterministic result",
                "score": 0.91,
                "retrieval_path": "content_chunk_workspace_scoped",
                "retrieval_mode": "deterministic_fallback",
                "embedding_status": "provider_disabled",
            },
            {
                "content_id": "m11c23-b",
                "chunk_id": "chunk-b",
                "text": "alpha debug metrics hub result",
                "score": 0.82,
                "hub_match": "hub-123",
                "retrieval_path": "hub_link_workspace_scoped",
            },
            {
                "content_id": "m11c23-a",
                "chunk_id": "chunk-a-dup",
                "text": "duplicate content should be counted before normalize",
                "score": 0.1,
                "retrieval_path": "content_chunk_workspace_scoped",
            },
            {
                "content_id": "m11c23-c",
                "chunk_id": "chunk-c",
                "text": "alpha debug metrics third result after limit",
                "score": 0.7,
                "retrieval_path": "content_chunk_workspace_scoped",
            },
        ]


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.dependencies.auth import require_permission
    from memory_lab.api.main import create_app
    import memory_lab.api.routers.retrieval as retrieval_router

    FakeStageMetricsAdapter.calls = []
    FakeStageMetricsAdapter.instances = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/example")
    monkeypatch.setattr(retrieval_router, "RetrievalAdapter", FakeStageMetricsAdapter)

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


def test_debug_false_keeps_normal_response_clean(monkeypatch):
    r = _client(monkeypatch).post(
        "/v1/retrieval/search",
        json={"query": "alpha debug metrics", "limit": 2, "debug": False},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "debug_metadata" not in body
    assert body["result_count"] == 2
    assert [item["content_id"] for item in body["results"]] == ["m11c23-a", "m11c23-b"]
    assert "retrieval_reason" in body["results"][0]  # M11C-2-2 diagnostics remain unchanged.


def test_debug_true_returns_safe_stage_metrics_without_changing_results(monkeypatch):
    r = _client(monkeypatch).post(
        "/v1/retrieval/search",
        json={"query": "alpha debug metrics", "limit": 2, "debug": True, "only_clean": True},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert [item["content_id"] for item in body["results"]] == ["m11c23-a", "m11c23-b"]
    assert body["result_count"] == 2

    debug = body["debug_metadata"]
    assert debug["requested"] is True
    assert "postgresql://" not in str(debug)

    metrics = debug["stage_metrics"]
    for key in (
        "adapter_search",
        "normalize",
        "deterministic_retrieval",
        "pgvector",
        "hub_inclusion",
        "graph_expansion",
        "dedup_filtering",
    ):
        assert key in metrics

    assert metrics["adapter_search"]["candidate_count"] == 4
    assert metrics["adapter_search"]["output_count"] == 4
    assert metrics["normalize"]["input_count"] == 4
    assert metrics["normalize"]["output_count"] == 3
    assert metrics["normalize"]["result_count_before_limit"] == 3
    assert metrics["normalize"]["result_count_after_limit"] == 2
    assert metrics["dedup_filtering"]["input_count"] == 4
    assert metrics["dedup_filtering"]["output_count"] == 3
    assert metrics["dedup_filtering"]["dropped_count"] == 1

    assert metrics["deterministic_retrieval"]["attempted"] is True
    assert metrics["deterministic_retrieval"]["used"] is True
    assert metrics["pgvector"]["attempted"] is True
    assert metrics["pgvector"]["used"] is False
    assert metrics["pgvector"]["skipped"] is True
    assert metrics["pgvector"]["reason"] == "provider_disabled"
    assert metrics["hub_inclusion"]["attempted"] is True
    assert metrics["hub_inclusion"]["used"] is True
    assert metrics["graph_expansion"]["attempted"] is True
    assert metrics["graph_expansion"]["used"] is False
    assert metrics["graph_expansion"]["skipped"] is True
    assert "provider_disabled" in debug["degraded_reasons"]


def test_debug_stage_metrics_descriptive_only_do_not_mutate_adapter_results(monkeypatch):
    r = _client(monkeypatch).post(
        "/v1/retrieval/search",
        json={"query": "alpha debug metrics", "limit": 3, "debug": True},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert [item["rank"] for item in body["results"]] == [1, 2, 3]
    assert [item["content_id"] for item in body["results"]] == ["m11c23-a", "m11c23-b", "m11c23-c"]
    assert FakeStageMetricsAdapter.calls[-1]["memory_types"] is None
