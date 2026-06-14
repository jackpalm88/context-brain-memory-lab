"""Read-only B15 graph health API router.

This router exposes deterministic, public-safe graph health signals from the
B15 service layer. It does not query private Context Brain, call providers,
write graph state, merge aliases, arbitrate truth, or resolve conflicts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.graph.alias_hygiene import AliasHygieneService
from memory_lab.graph.health_models import DEFAULT_NON_CLAIMS
from memory_lab.graph.health_service import GraphHealthService
from memory_lab.graph.hub_recall_health import HubRecallHealthService
from memory_lab.graph.repository_reader import RepositoryGraphHealthReader
from memory_lab.reports.graph_health_report import GraphHealthReportGenerator

router = APIRouter(prefix="/v1", tags=["graph-health"])

READ_PERMISSION = "hubs.read"
GRAPH_HEALTH_MODES = {"sample", "repository"}


def get_graph_health_repository_reader() -> Optional[RepositoryGraphHealthReader]:
    """Return a repository reader when a repository dependency is wired.

    The public API must not silently treat sample data as repository data. Until a
    production DB/session provider is explicitly wired, repository mode returns
    an explicit unavailable snapshot. Tests may override this dependency with a
    fake RepositoryGraphHealthReader(row_sets=...).
    """
    return None


def _sample_graph_health_payload() -> Dict[str, Any]:
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
    return _graph_health_api_payload(report, mode="sample", data_source="sample")


def _graph_health_api_payload(
    report: Dict[str, Any],
    *,
    mode: Optional[str] = None,
    data_source: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "mode": mode or report.get("mode", "unknown"),
        "data_source": data_source or report.get("data_source", "unknown"),
        "health_score": report["health_score"],
        "component_scores": report["component_scores"],
        "warnings": report["warnings"],
        "limitations": report["limitations"],
        "non_claims": report["non_claims"],
    }


def _repository_reader_from_request(request: Request) -> Optional[RepositoryGraphHealthReader]:
    override = request.app.dependency_overrides.get(get_graph_health_repository_reader)
    if override is not None:
        return override()
    return get_graph_health_repository_reader()


@router.get("/graph/health")
def graph_health(
    request: Request,
    mode: str = Query("sample"),
    auth: AuthContext = Depends(require_permission(READ_PERMISSION)),
) -> Dict[str, Any]:
    """Return deterministic graph health signals.

    Default/sample mode preserves the B15 deterministic fixture behavior.
    Repository mode must be requested explicitly and never falls back to sample
    data when the repository dependency is unavailable.
    """
    del auth
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in GRAPH_HEALTH_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_graph_health_mode",
                "allowed_modes": sorted(GRAPH_HEALTH_MODES),
            },
        )

    if normalized_mode == "sample":
        return _sample_graph_health_payload()

    repository_reader = _repository_reader_from_request(request)
    reader = repository_reader or RepositoryGraphHealthReader()
    if repository_reader is None:
        snapshot = reader.unavailable_snapshot("repository_dependency_unavailable")
    else:
        snapshot = reader.read_snapshot()
    report = GraphHealthReportGenerator().generate_from_repository_snapshot(
        scenario_name="api_repository_graph_health",
        snapshot=snapshot,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return _graph_health_api_payload(report)


def _sample_hub_recall_payload(hub_id: str) -> Dict[str, Any]:
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
    return _hub_recall_api_payload(report, hub_id=hub_id, mode="sample", data_source="sample")


def _hub_recall_api_payload(
    report: Any,
    *,
    hub_id: str,
    mode: str,
    data_source: str,
    extra_limitations: Optional[list[str]] = None,
) -> Dict[str, Any]:
    limitations = list(report.limitations)
    if extra_limitations:
        limitations.extend(extra_limitations)
    return {
        "mode": mode,
        "data_source": data_source,
        "hub_id": report.hub_id or hub_id,
        "linked_count": report.metrics.linked_count,
        "searchable_linked_count": report.metrics.searchable_linked_count,
        "retrieval_observed_count": report.metrics.retrieval_observed_count,
        "findings": [finding.model_dump() for finding in report.findings],
        "warnings": [warning.model_dump() for warning in report.warnings],
        "limitations": sorted(set(limitations)),
        "non_claims": report.non_claims,
    }


@router.get("/hubs/{hub_id}/recall-health")
def hub_recall_health(
    request: Request,
    hub_id: str,
    mode: str = Query("sample"),
    auth: AuthContext = Depends(require_permission(READ_PERMISSION)),
) -> Dict[str, Any]:
    """Return deterministic hub recall health signals for the requested hub id."""
    del auth
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in GRAPH_HEALTH_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_hub_recall_health_mode",
                "allowed_modes": sorted(GRAPH_HEALTH_MODES),
            },
        )

    if normalized_mode == "sample":
        return _sample_hub_recall_payload(hub_id)

    repository_reader = _repository_reader_from_request(request)
    if repository_reader is None:
        report = HubRecallHealthService().evaluate(
            content_items=[],
            hub_links={hub_id: []},
            retrieval_observations={},
            hub_id=hub_id,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        return _hub_recall_api_payload(
            report,
            hub_id=hub_id,
            mode="unavailable",
            data_source="unavailable",
            extra_limitations=["repository_dependency_unavailable", "repository_reader_unavailable"],
        )

    inputs = repository_reader.read_hub_recall_inputs(hub_id)
    report = HubRecallHealthService().evaluate(
        content_items=inputs.get("content_items", []),
        hub_links=inputs.get("hub_links", {hub_id: []}),
        retrieval_observations=inputs.get("retrieval_observations", {}),
        hub_id=hub_id,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return _hub_recall_api_payload(
        report,
        hub_id=hub_id,
        mode="repository",
        data_source="repository",
        extra_limitations=list(inputs.get("limitations", ())) + list(inputs.get("unknown_fields", ())),
    )


def _alias_candidates_api_payload(
    *,
    report: Any,
    mode: str,
    data_source: str,
    extra_limitations: Optional[list[str]] = None,
) -> Dict[str, Any]:
    candidates = [candidate.model_dump() for candidate in report.candidates]
    limitations = list(report.limitations)
    if extra_limitations:
        limitations.extend(extra_limitations)
    return {
        "mode": mode,
        "data_source": data_source,
        "alias_candidate_groups": candidates,
        "review_required": any(candidate["requires_human_review"] for candidate in candidates),
        "warnings": [warning.model_dump() for warning in report.warnings],
        "limitations": sorted(set(limitations)),
        "non_claims": report.non_claims or DEFAULT_NON_CLAIMS,
    }


def _sample_alias_candidates_payload() -> Dict[str, Any]:
    report = AliasHygieneService().generate_candidates(
        ["D.O.M.A", "DOMA", "doma", "Context Brain", "Context_Brain"]
    )
    return _alias_candidates_api_payload(report=report, mode="sample", data_source="sample")


@router.get("/graph/alias-candidates")
def graph_alias_candidates(
    request: Request,
    mode: str = Query("sample"),
    auth: AuthContext = Depends(require_permission(READ_PERMISSION)),
) -> Dict[str, Any]:
    """Return deterministic alias candidate groups requiring human review."""
    del auth
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in GRAPH_HEALTH_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_alias_candidates_mode",
                "allowed_modes": sorted(GRAPH_HEALTH_MODES),
            },
        )

    if normalized_mode == "sample":
        return _sample_alias_candidates_payload()

    repository_reader = _repository_reader_from_request(request)
    if repository_reader is None:
        report = AliasHygieneService().generate_candidates([])
        return _alias_candidates_api_payload(
            report=report,
            mode="unavailable",
            data_source="unavailable",
            extra_limitations=["repository_dependency_unavailable", "repository_reader_unavailable"],
        )

    inputs = repository_reader.read_alias_candidate_inputs()
    report = AliasHygieneService().generate_candidates(inputs.get("alias_labels", []))
    extra_limitations = list(inputs.get("limitations", ())) + list(inputs.get("unknown_fields", ()))
    if not inputs.get("alias_labels") and not inputs.get("alias_candidates"):
        extra_limitations.append("repository_alias_inputs_empty")
    return _alias_candidates_api_payload(
        report=report,
        mode="repository",
        data_source="repository",
        extra_limitations=extra_limitations,
    )


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
