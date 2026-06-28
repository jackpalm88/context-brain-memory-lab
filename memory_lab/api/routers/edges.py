from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/edges", tags=["edges"])



class EdgeUpdateRequest(BaseModel):
    edge_type: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    reason: Optional[str] = None
    confidence: Optional[float] = None


class InferredEdgeReviewRequest(BaseModel):
    source_hub_id: str
    target_hub_id: str
    edge_type: str
    reason: Optional[str] = None
    confidence: Optional[float] = None
    note: Optional[str] = None


class EdgeCreateRequest(BaseModel):
    source_hub_id: str
    target_hub_id: str
    edge_type: str
    status: Optional[str] = "manual"
    origin: Optional[str] = "manual"
    confidence: Optional[float] = None
    reason: Optional[str] = None
    note: Optional[str] = None


@router.post("")
def create_edge(req: EdgeCreateRequest, auth: AuthContext = Depends(require_permission("edges.create"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    try:
        return adapter.create_edge(req.model_dump(), workspace_id=auth.workspace_id, created_by=auth.auth_subject_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{edge_id}")
def get_edge(edge_id: str, auth: AuthContext = Depends(require_permission("edges.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    edge = adapter.get_edge(edge_id, workspace_id=auth.workspace_id)
    if not edge:
        raise HTTPException(status_code=404, detail="edge not found")
    return edge


@router.get("")
def list_edges(
    hub_id: Optional[str] = None,
    include_archived: bool = Query(False),
    include_rejected: bool = Query(False),
    auth: AuthContext = Depends(require_permission("edges.read")),
) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    edges = adapter.list_edges(hub_id, include_archived, include_rejected, workspace_id=auth.workspace_id)
    return {"edges": edges, "count": len(edges), "workspace_id": auth.workspace_id}


@router.post("/{edge_id}/archive")
def archive_edge(edge_id: str, auth: AuthContext = Depends(require_permission("edges.archive"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.archive_edge(edge_id, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="edge not found or already archived")
    return {"edge_id": edge_id, "archived": True, "edge": row, "workspace_id": auth.workspace_id}


@router.patch("/{edge_id}")
def update_edge(edge_id: str, req: EdgeUpdateRequest, auth: AuthContext = Depends(require_permission("edges.update"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    updates = req.model_dump(exclude_none=True)
    if "edge_type" in updates:
        updates["type"] = updates.pop("edge_type")
    try:
        row = adapter.update_edge(edge_id, updates, workspace_id=auth.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="edge not found")
    return {"edge": row, "updated": True, "workspace_id": auth.workspace_id}


@router.post("/inferred/approve")
def approve_inferred_edge(req: InferredEdgeReviewRequest, auth: AuthContext = Depends(require_permission("edges.create"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    try:
        edge = adapter.approve_inferred_edge(
            source_hub_id=req.source_hub_id,
            target_hub_id=req.target_hub_id,
            edge_type=req.edge_type,
            reason=req.reason,
            confidence=req.confidence,
            note=req.note,
            workspace_id=auth.workspace_id,
            created_by=auth.auth_subject_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"edge": edge, "approved": True, "workspace_id": auth.workspace_id}


@router.post("/inferred/reject")
def reject_inferred_edge(req: InferredEdgeReviewRequest, auth: AuthContext = Depends(require_permission("edges.create"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    try:
        edge = adapter.reject_inferred_edge(
            source_hub_id=req.source_hub_id,
            target_hub_id=req.target_hub_id,
            edge_type=req.edge_type,
            reason=req.reason,
            note=req.note,
            workspace_id=auth.workspace_id,
            created_by=auth.auth_subject_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"edge": edge, "rejected": True, "workspace_id": auth.workspace_id}
