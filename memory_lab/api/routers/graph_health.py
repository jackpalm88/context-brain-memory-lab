"""Read-only B15 graph health API router.

This router exposes deterministic, public-safe graph health signals from the
B15 service layer. It does not query private Context Brain, call providers,
write graph state, merge aliases, arbitrate truth, or resolve conflicts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.graph.alias_hygiene import AliasHygieneService
from memory_lab.graph.health_models import DEFAULT_NON_CLAIMS
from memory_lab.graph.health_service import GraphHealthService
from memory_lab.graph.hub_recall_health import HubRecallHealthService
from memory_lab.reports.graph_health_report import GraphHealthReportGenerator

router = APIRouter(prefix="/v1", tags=["graph-health"])

READ_PERMISSION = "hubs.read"


@router.get("/graph/health")
def graph_health(auth: AuthContext = Depends(require_permission(READ_PERMISSION))) -> Dict[str, Any]:
    """Return deterministic graph health signals using sample/injected data."""
    del auth
    report = GraphHealthReportGenerator().generate(
        scenario_name="api_sample_graph_health",
        nodes=["api-a", "api-b", "api-c"],
        edges=[("api-a", "api-b"), ("api-b", "api-c")],
        content_items=[
            {
                "content_id": "api-a",
                "searchable": True,
                "embedding_present": True,
                "graph_reachable": True,
            },
            {
                "content_id": "api-b",
                "searchable": True,
                "embedding_present": True,
                "graph_reachable": True,
            },
            {
                "content_id": "api-c",
                "searchable": False,
                "embedding_present": False,
                "graph_reachable": True,
            },
        ],
        hub_links={"api-hub": ["api-a", "api-b", "api-c"]},
        retrieval_observations={
            ("api-hub", "api-a"): True,
            ("api-hub", "api-b"): True,
            ("api-hub", "api-c"): False,
        },
        alias_labels=["Context Brain", "Memory Lab", "Graph Health"],
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return {
        "health_score": report["health_score"],
        "component_scores": report["component_scores"],
        "warnings": report["warnings"],
        "limitations": report["limitations"],
        "non_claims": report["non_claims"],
    }


@router.get("/hubs/{hub_id}/recall-health")
def hub_recall_health(
    hub_id: str,
    auth: AuthContext = Depends(require_permission(READ_PERMISSION)),
) -> Dict[str, Any]:
    """Return deterministic hub recall health signals for the requested hub id."""
    del auth
    content_items = [
        {
            "content_id": f"{hub_id}-linked-searchable",
            "searchable": True,
            "embedding_present": True,
            "graph_reachable": True,
        },
        {
            "content_id": f"{hub_id}-linked-pending",
            "searchable": False,
            "embedding_present": False,
            "graph_reachable": False,
            "indexing_status": "pending",
        },
    ]
    hub_links = {hub_id: [item["content_id"] for item in content_items]}
    retrieval_observations = {
        (hub_id, f"{hub_id}-linked-searchable"): True,
        (hub_id, f"{hub_id}-linked-pending"): False,
    }
    report = HubRecallHealthService().evaluate(
        content_items=content_items,
        hub_links=hub_links,
        retrieval_observations=retrieval_observations,
        hub_id=hub_id,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return {
        "hub_id": report.hub_id or hub_id,
        "linked_count": report.metrics.linked_count,
        "searchable_linked_count": report.metrics.searchable_linked_count,
        "retrieval_observed_count": report.metrics.retrieval_observed_count,
        "findings": [finding.model_dump() for finding in report.findings],
        "warnings": [warning.model_dump() for warning in report.warnings],
        "limitations": report.limitations,
        "non_claims": report.non_claims,
    }


@router.get("/graph/alias-candidates")
def graph_alias_candidates(
    auth: AuthContext = Depends(require_permission(READ_PERMISSION)),
) -> Dict[str, Any]:
    """Return deterministic alias candidate groups requiring human review."""
    del auth
    report = AliasHygieneService().generate_candidates(
        ["D.O.M.A", "DOMA", "doma", "Context Brain", "Context_Brain"]
    )
    candidates = [candidate.model_dump() for candidate in report.candidates]
    return {
        "alias_candidate_groups": candidates,
        "review_required": any(candidate["requires_human_review"] for candidate in candidates),
        "warnings": [warning.model_dump() for warning in report.warnings],
        "limitations": report.limitations,
        "non_claims": report.non_claims or DEFAULT_NON_CLAIMS,
    }


def sample_graph_health_report() -> Dict[str, Any]:
    """Callable helper for tests and local report generation without HTTP."""
    return GraphHealthService().evaluate(
        nodes=["sample-a", "sample-b"],
        edges=[("sample-a", "sample-b")],
        content_items=[
            {
                "content_id": "sample-a",
                "searchable": True,
                "embedding_present": True,
                "graph_reachable": True,
            }
        ],
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ).model_dump()
