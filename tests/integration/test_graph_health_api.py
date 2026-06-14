from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
from memory_lab.api.routers.graph_health import get_graph_health_repository_reader
from memory_lab.graph.repository_reader import RepositoryGraphHealthReader

SUBJECT = "00000000-0000-0000-0000-000000000b15"
WORKSPACE = "00000000-0000-0000-0000-000000000015"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _forbidden_top_level() -> set[str]:
    return {
        "merge_" + "entities",
        "create_" + "relation",
        "truth_" + "decision",
        "ver" + "dict",
        "provider_" + "synthesis",
    }


def _auth_override() -> AuthContext:
    return AuthContext(
        auth_subject_id=SUBJECT,
        subject_type="user",
        workspace_id=WORKSPACE,
        role="reader",
        auth_method="test",
    )


def _client(*, repository_reader_override=None, auth: bool = True) -> TestClient:
    app = create_app()

    if auth:
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in getattr(dependant, "dependencies", []):
                call = getattr(dep, "call", None)
                if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                    closure_values = [cell.cell_contents for cell in call.__closure__]
                    if "hubs.read" in closure_values:
                        app.dependency_overrides[call] = _auth_override
        app.dependency_overrides[require_permission("hubs.read")] = _auth_override

    if repository_reader_override is not None:
        app.dependency_overrides[get_graph_health_repository_reader] = repository_reader_override

    return TestClient(app)


def _repository_rows():
    return {
        "content_items": [
            {"content_id": "repo-c1", "workspace_id": WORKSPACE},
            {"content_id": "repo-c2", "workspace_id": WORKSPACE},
        ],
        "content_chunks": [
            {
                "chunk_id": "repo-ch1",
                "content_id": "repo-c1",
                "workspace_id": WORKSPACE,
                "chunk_index": 0,
                "chunk_text": "indexed repository item",
                "embedding": [0.1, 0.2],
                "created_at": NOW,
            },
            {
                "chunk_id": "repo-ch2",
                "content_id": "repo-c2",
                "workspace_id": WORKSPACE,
                "chunk_index": 0,
                "chunk_text": "repository item missing embedding",
                "embedding": None,
                "created_at": NOW,
            },
        ],
        "cb_hubs": [
            {"hub_id": "repo-h1", "workspace_uuid": WORKSPACE, "title": "Graph Health", "aliases": ["graph hygiene"]}
        ],
        "cb_hub_content": [
            {"hub_id": "repo-h1", "content_id": "repo-c1", "workspace_id": WORKSPACE},
            {"hub_id": "repo-h1", "content_id": "repo-c2", "workspace_id": WORKSPACE},
        ],
        "cb_edges": [{"from_node": "repo-c1", "relation": "related", "to_node": "repo-h1", "workspace_id": WORKSPACE}],
        "cb_hub_edges": [],
        "cb_aliases": [],
        "cb_alias_candidates": [
            {"term_a": "Graph Health", "term_b": "graph hygiene", "score": 0.91, "status": "pending"},
            {"term_a": "DOMA", "term_b": "doma", "score": 0.93, "status": "pending"}
        ],
        "cb_query_log": [],
    }


def _fake_repository_reader() -> RepositoryGraphHealthReader:
    return RepositoryGraphHealthReader(row_sets=_repository_rows(), workspace_id=WORKSPACE, now_fn=lambda: NOW)


def test_graph_health_endpoint_default_sample_read_only_contract() -> None:
    response = _client().get("/v1/graph/health")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {
        "mode",
        "data_source",
        "health_score",
        "component_scores",
        "warnings",
        "limitations",
        "non_claims",
    }
    assert body["mode"] == "sample"
    assert body["data_source"] == "sample"
    assert isinstance(body["health_score"], int)
    assert {"topology_score", "index_searchability_score", "hub_recall_score", "alias_hygiene_score", "consistency_score"}.issubset(
        body["component_scores"].keys()
    )
    assert any(w["code"] == "MISSING_ITEM_EMBEDDING" for w in body["warnings"])
    assert "no_graph_mutation_or_automatic_merge" in body["non_claims"]
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_graph_health_endpoint_explicit_sample_remains_sample_static_behavior() -> None:
    response = _client().get("/v1/graph/health?mode=sample")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "sample"
    assert body["data_source"] == "sample"
    assert any(w["code"] == "MISSING_ITEM_EMBEDDING" for w in body["warnings"])
    assert "no_full_context_brain_claim" in body["non_claims"]


def test_graph_health_sample_mode_does_not_resolve_repository_reader() -> None:
    def forbidden_reader():
        raise AssertionError("sample mode must not use repository reader")

    response = _client(repository_reader_override=forbidden_reader).get("/v1/graph/health?mode=sample")
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "sample"


def test_graph_health_repository_mode_uses_fake_reader_and_returns_repository_metadata() -> None:
    response = _client(repository_reader_override=_fake_repository_reader).get("/v1/graph/health?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "repository"
    assert body["data_source"] == "repository"
    assert body["health_score"] >= 0
    warning_codes = {warning["code"] for warning in body["warnings"]}
    assert "MISSING_ITEM_EMBEDDING" in warning_codes
    assert "NULL_EMBEDDING_BACKLOG" in warning_codes
    assert "REPOSITORY_CHUNK_EMBEDDING_MISSING_OR_NULL" in warning_codes
    assert "retrieval_observed_unavailable_or_not_provided" in body["limitations"]
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_graph_health_repository_unavailable_is_explicit_and_not_sample_fallback() -> None:
    response = _client().get("/v1/graph/health?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "unavailable"
    assert body["data_source"] == "unavailable"
    assert body["mode"] != "sample"
    assert body["data_source"] != "sample"
    assert "repository_dependency_unavailable" in body["limitations"]
    assert "repository_reader_unavailable" in body["limitations"]


def test_graph_health_invalid_mode_returns_http_400() -> None:
    response = _client().get("/v1/graph/health?mode=auto")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"]["error"] == "invalid_graph_health_mode"
    assert body["detail"]["allowed_modes"] == ["repository", "sample"]


def test_graph_health_repository_mode_preserves_hubs_read_permission() -> None:
    app = create_app()
    graph_route = next(route for route in app.routes if getattr(route, "path", "") == "/v1/graph/health")
    dependant = getattr(graph_route, "dependant", None)
    dependency_calls = [getattr(dep, "call", None) for dep in getattr(dependant, "dependencies", [])]
    closure_values = [
        cell.cell_contents
        for call in dependency_calls
        for cell in (getattr(call, "__closure__", None) or [])
    ]
    assert "hubs.read" in closure_values


def _assert_hub_recall_sample_body(body: dict, hub_id: str = "test-hub") -> None:
    assert set(body) == {
        "mode",
        "data_source",
        "hub_id",
        "linked_count",
        "searchable_linked_count",
        "retrieval_observed_count",
        "findings",
        "warnings",
        "limitations",
        "non_claims",
    }
    assert body["mode"] == "sample"
    assert body["data_source"] == "sample"
    assert body["hub_id"] == hub_id
    assert body["linked_count"] == 2
    assert body["searchable_linked_count"] == 1
    assert body["retrieval_observed_count"] == 1
    assert body["findings"]
    assert any(w["code"] == "HUB_LINKED_NOT_SEARCHABLE" for w in body["warnings"])
    assert any(w["code"] == "HUB_LINKED_NOT_RETRIEVED" for w in body["warnings"])
    assert "no_graph_mutation_or_automatic_merge" in body["non_claims"]
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_hub_recall_health_endpoint_default_sample_behavior() -> None:
    response = _client().get("/v1/hubs/test-hub/recall-health")
    assert response.status_code == 200, response.text
    _assert_hub_recall_sample_body(response.json())


def test_hub_recall_health_endpoint_explicit_sample_behavior() -> None:
    response = _client().get("/v1/hubs/test-hub/recall-health?mode=sample")
    assert response.status_code == 200, response.text
    _assert_hub_recall_sample_body(response.json())


def test_hub_recall_sample_mode_does_not_resolve_repository_reader() -> None:
    def forbidden_reader():
        raise AssertionError("hub recall sample mode must not use repository reader")

    response = _client(repository_reader_override=forbidden_reader).get("/v1/hubs/test-hub/recall-health?mode=sample")
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "sample"


def test_hub_recall_repository_mode_uses_fake_reader_and_returns_repository_metadata() -> None:
    response = _client(repository_reader_override=_fake_repository_reader).get("/v1/hubs/repo-h1/recall-health?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "repository"
    assert body["data_source"] == "repository"
    assert body["hub_id"] == "repo-h1"
    assert body["linked_count"] == 2
    assert body["searchable_linked_count"] == 1
    assert body["retrieval_observed_count"] == 0
    assert "retrieval_observed_not_available" in body["limitations"]
    assert any(w["code"] == "HUB_LINKED_NOT_SEARCHABLE" for w in body["warnings"])
    assert not any(w["code"] == "HUB_LINKED_NOT_RETRIEVED" for w in body["warnings"])
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_hub_recall_repository_unavailable_is_explicit_and_not_sample_fallback() -> None:
    response = _client().get("/v1/hubs/test-hub/recall-health?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "unavailable"
    assert body["data_source"] == "unavailable"
    assert body["mode"] != "sample"
    assert body["data_source"] != "sample"
    assert body["hub_id"] == "test-hub"
    assert body["linked_count"] == 0
    assert "repository_dependency_unavailable" in body["limitations"]
    assert "repository_reader_unavailable" in body["limitations"]


def test_hub_recall_invalid_mode_returns_http_400() -> None:
    response = _client().get("/v1/hubs/test-hub/recall-health?mode=auto")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"]["error"] == "invalid_hub_recall_health_mode"
    assert body["detail"]["allowed_modes"] == ["repository", "sample"]


def test_hub_recall_repository_mode_preserves_hubs_read_permission() -> None:
    app = create_app()
    graph_route = next(route for route in app.routes if getattr(route, "path", "") == "/v1/hubs/{hub_id}/recall-health")
    dependant = getattr(graph_route, "dependant", None)
    dependency_calls = [getattr(dep, "call", None) for dep in getattr(dependant, "dependencies", [])]
    closure_values = [
        cell.cell_contents
        for call in dependency_calls
        for cell in (getattr(call, "__closure__", None) or [])
    ]
    assert "hubs.read" in closure_values


def _assert_alias_sample_body(body: dict) -> None:
    assert set(body) == {
        "mode",
        "data_source",
        "alias_candidate_groups",
        "review_required",
        "warnings",
        "limitations",
        "non_claims",
    }
    assert body["mode"] == "sample"
    assert body["data_source"] == "sample"
    assert body["review_required"] is True
    assert len(body["alias_candidate_groups"]) >= 2
    assert all(candidate["requires_human_review"] is True for candidate in body["alias_candidate_groups"])
    assert all(candidate["mutation_allowed"] is False for candidate in body["alias_candidate_groups"])
    assert all(candidate["confidence"] <= 0.8 for candidate in body["alias_candidate_groups"])
    assert any(w["code"] == "ALIAS_CANDIDATE_REVIEW_REQUIRED" for w in body["warnings"])
    assert "no_graph_mutation_or_automatic_merge" in body["non_claims"]
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_alias_candidates_endpoint_default_sample_behavior() -> None:
    response = _client().get("/v1/graph/alias-candidates")
    assert response.status_code == 200, response.text
    _assert_alias_sample_body(response.json())


def test_alias_candidates_endpoint_explicit_sample_behavior() -> None:
    response = _client().get("/v1/graph/alias-candidates?mode=sample")
    assert response.status_code == 200, response.text
    _assert_alias_sample_body(response.json())


def test_alias_candidates_sample_mode_does_not_resolve_repository_reader() -> None:
    def forbidden_reader():
        raise AssertionError("alias sample mode must not use repository reader")

    response = _client(repository_reader_override=forbidden_reader).get("/v1/graph/alias-candidates?mode=sample")
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "sample"


def test_alias_candidates_repository_mode_uses_fake_reader_and_remains_review_only() -> None:
    response = _client(repository_reader_override=_fake_repository_reader).get("/v1/graph/alias-candidates?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "repository"
    assert body["data_source"] == "repository"
    assert body["review_required"] is True
    assert body["alias_candidate_groups"]
    assert any(set(candidate["terms"]) == {"DOMA", "doma"} for candidate in body["alias_candidate_groups"])
    assert all(candidate["requires_human_review"] is True for candidate in body["alias_candidate_groups"])
    assert all(candidate["mutation_allowed"] is False for candidate in body["alias_candidate_groups"])
    assert all(candidate["confidence"] <= 0.8 for candidate in body["alias_candidate_groups"])
    assert any(w["code"] == "ALIAS_CANDIDATE_REVIEW_REQUIRED" for w in body["warnings"])
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_alias_candidates_repository_unavailable_is_explicit_and_not_sample_fallback() -> None:
    response = _client().get("/v1/graph/alias-candidates?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "unavailable"
    assert body["data_source"] == "unavailable"
    assert body["mode"] != "sample"
    assert body["data_source"] != "sample"
    assert body["alias_candidate_groups"] == []
    assert body["review_required"] is False
    assert "no_alias_candidates_detected_from_provided_labels" in body["limitations"]
    assert "repository_dependency_unavailable" in body["limitations"]
    assert "repository_reader_unavailable" in body["limitations"]


def test_alias_candidates_empty_repository_inputs_do_not_invent_candidates() -> None:
    def empty_reader() -> RepositoryGraphHealthReader:
        return RepositoryGraphHealthReader(row_sets={}, workspace_id=WORKSPACE, now_fn=lambda: NOW)

    response = _client(repository_reader_override=empty_reader).get("/v1/graph/alias-candidates?mode=repository")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["mode"] == "repository"
    assert body["data_source"] == "repository"
    assert body["alias_candidate_groups"] == []
    assert body["review_required"] is False
    assert "repository_alias_inputs_empty" in body["limitations"]
    assert "no_alias_candidates_detected_from_provided_labels" in body["limitations"]


def test_alias_candidates_invalid_mode_returns_http_400() -> None:
    response = _client().get("/v1/graph/alias-candidates?mode=auto")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"]["error"] == "invalid_alias_candidates_mode"
    assert body["detail"]["allowed_modes"] == ["repository", "sample"]


def test_alias_candidates_repository_mode_preserves_hubs_read_permission() -> None:
    app = create_app()
    graph_route = next(route for route in app.routes if getattr(route, "path", "") == "/v1/graph/alias-candidates")
    dependant = getattr(graph_route, "dependant", None)
    dependency_calls = [getattr(dep, "call", None) for dep in getattr(dependant, "dependencies", [])]
    closure_values = [
        cell.cell_contents
        for call in dependency_calls
        for cell in (getattr(call, "__closure__", None) or [])
    ]
    assert "hubs.read" in closure_values


def test_no_mutation_methods_registered_for_graph_health_paths() -> None:
    app = create_app()
    route_methods = {
        getattr(route, "path", ""): getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "") in {
            "/v1/graph/health",
            "/v1/hubs/{hub_id}/recall-health",
            "/v1/graph/alias-candidates",
        }
    }
    assert route_methods["/v1/graph/health"] == {"GET"}
    assert route_methods["/v1/hubs/{hub_id}/recall-health"] == {"GET"}
    assert route_methods["/v1/graph/alias-candidates"] == {"GET"}
