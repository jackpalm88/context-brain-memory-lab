from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.decisions import (
    DecisionConflictsResponse,
    DecisionCreate,
    DecisionCreateResponse,
    DecisionFull,
    DecisionLineageResponse,
    DecisionListResponse,
    DecisionsByContentResponse,
    DecisionStatusUpdate,
    DecisionTimelineResponse,
    DecisionStore,
)

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _store() -> DecisionStore:
    return DecisionStore(get_settings().database_url)


@router.get("/conflicts", response_model=DecisionConflictsResponse)
def list_decision_conflicts(auth: AuthContext = Depends(require_permission("decisions.read"))):
    return _store().list_conflicts(workspace_id=auth.workspace_id)


@router.get("/timeline", response_model=DecisionTimelineResponse)
def get_decision_timeline(
    hub_id: Optional[UUID] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tag filter"),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_permission("decisions.read")),
):
    return _store().get_timeline(hub_id=hub_id, tags=tags, limit=limit, workspace_id=auth.workspace_id)


@router.get("/", response_model=DecisionListResponse)
def list_decisions(
    status: Optional[str] = Query(None, pattern="^(active|superseded|reversed|draft)$"),
    hub_id: Optional[UUID] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    auth: AuthContext = Depends(require_permission("decisions.read")),
):
    return _store().list_decisions(status=status, hub_id=hub_id, limit=limit, workspace_id=auth.workspace_id)


@router.post("/", response_model=DecisionCreateResponse, status_code=201)
def create_decision_memory(payload: DecisionCreate, auth: AuthContext = Depends(require_permission("decisions.create"))):
    try:
        row = _store().create_decision(payload, workspace_id=auth.workspace_id, created_by_subject=auth.auth_subject_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DecisionCreateResponse(
        decision_id=row["decision_id"],
        title=row["title"],
        decision_status=row["decision_status"],
        created_at=row["created_at"],
    )


@router.get("/by-content/{content_id}", response_model=DecisionsByContentResponse)
def list_decisions_for_content(
    content_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_permission("decisions.read")),
):
    """CF-002 Stage 1: which decisions reference this content item?

    The derived reverse read over the two existing link columns — canonical
    content_id (Stage-2-activated) and caller-declared source_content_ids.
    Unknown or foreign-workspace content ids return 200 with count=0, never
    404: the empty list neither confirms nor denies the content's existence.
    """
    return _store().list_decisions_for_content(
        content_id=content_id, limit=limit, workspace_id=auth.workspace_id
    )


@router.get("/{decision_id}/lineage", response_model=DecisionLineageResponse)
def get_decision_lineage(decision_id: UUID, auth: AuthContext = Depends(require_permission("decisions.read"))):
    try:
        return _store().get_lineage(decision_id, workspace_id=auth.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{decision_id}", response_model=DecisionFull)
def explain_decision(decision_id: UUID, auth: AuthContext = Depends(require_permission("decisions.read"))):
    try:
        return _store().explain_decision(decision_id, workspace_id=auth.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{decision_id}/status", response_model=DecisionFull)
def update_decision_status(decision_id: UUID, payload: DecisionStatusUpdate, auth: AuthContext = Depends(require_permission("decisions.update"))):
    try:
        return _store().update_status(decision_id, payload.decision_status, workspace_id=auth.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
