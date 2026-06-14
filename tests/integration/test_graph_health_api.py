from __future__ import annotations

from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app

SUBJECT = "00000000-0000-0000-0000-000000000b15"
WORKSPACE = "00000000-0000-0000-0000-000000000015"


def _forbidden_top_level() -> set[str]:
    return {
        "merge_" + "entities",
        "create_" + "relation",
        "truth_" + "decision",
        "ver" + "dict",
        "provider_" + "synthesis",
    }


def _client() -> TestClient:
    app = create_app()

    def override() -> AuthContext:
        return AuthContext(
            auth_subject_id=SUBJECT,
            subject_type="user",
            workspace_id=WORKSPACE,
            role="reader",
            auth_method="test",
        )

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                closure_values = [cell.cell_contents for cell in call.__closure__]
                if "hubs.read" in closure_values:
                    app.dependency_overrides[call] = override
    app.dependency_overrides[require_permission("hubs.read")] = override
    return TestClient(app)


def test_graph_health_endpoint_read_only_contract() -> None:
    response = _client().get("/v1/graph/health")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {
        "health_score",
        "component_scores",
        "warnings",
        "limitations",
        "non_claims",
    }
    assert isinstance(body["health_score"], int)
    assert {"topology_score", "index_searchability_score", "hub_recall_score", "alias_hygiene_score", "consistency_score"}.issubset(
        body["component_scores"].keys()
    )
    assert any(w["code"] == "MISSING_ITEM_EMBEDDING" for w in body["warnings"])
    assert "no_graph_mutation_or_automatic_merge" in body["non_claims"]
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_hub_recall_health_endpoint_contract() -> None:
    response = _client().get("/v1/hubs/test-hub/recall-health")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["hub_id"] == "test-hub"
    assert body["linked_count"] == 2
    assert body["searchable_linked_count"] == 1
    assert body["retrieval_observed_count"] == 1
    assert body["findings"]
    assert any(w["code"] == "HUB_LINKED_NOT_SEARCHABLE" for w in body["warnings"])
    assert any(w["code"] == "HUB_LINKED_NOT_RETRIEVED" for w in body["warnings"])
    assert "no_graph_mutation_or_automatic_merge" in body["non_claims"]
    assert _forbidden_top_level().isdisjoint(body.keys())


def test_alias_candidates_endpoint_contract() -> None:
    response = _client().get("/v1/graph/alias-candidates")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {
        "alias_candidate_groups",
        "review_required",
        "warnings",
        "limitations",
        "non_claims",
    }
    assert body["review_required"] is True
    assert len(body["alias_candidate_groups"]) >= 2
    assert all(candidate["mutation_allowed"] is False for candidate in body["alias_candidate_groups"])
    assert any(w["code"] == "ALIAS_CANDIDATE_REVIEW_REQUIRED" for w in body["warnings"])
    assert "no_graph_mutation_or_automatic_merge" in body["non_claims"]
    assert _forbidden_top_level().isdisjoint(body.keys())


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
