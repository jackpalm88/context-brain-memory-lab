from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/content", tags=["content"])


class ContentCreateRequest(BaseModel):
    content: Optional[str] = None
    workspace_id: Optional[str] = None


class QuickSummaryRequest(BaseModel):
    quick_summary: str = Field(..., max_length=500)


VALID_NODE_TYPES = frozenset({
    "decision", "fact", "hypothesis", "question", "playbook",
    "concept", "source", "task", "event", "raw_note",
})


class NodeTypeRequest(BaseModel):
    node_type: str


@router.post("")
def create_content(req: ContentCreateRequest, auth: AuthContext = Depends(require_permission("content.create"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_content_minimal(
        content=req.content,
        workspace_id=auth.workspace_id,
        workspace_source=auth.workspace_source,
        created_by_subject=auth.auth_subject_id,
    )


@router.get("/{content_id}")
def get_content(content_id: str, auth: AuthContext = Depends(require_permission("content.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_minimal(content_id, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row


@router.get("/{content_id}/metadata")
def get_content_metadata(content_id: str, auth: AuthContext = Depends(require_permission("content.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_metadata(content_id, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row


@router.patch("/{content_id}/quick-summary")
def set_quick_summary(content_id: str, req: QuickSummaryRequest, auth: AuthContext = Depends(require_permission("content.update"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.set_quick_summary(
        content_id=content_id,
        quick_summary=req.quick_summary,
        workspace_id=auth.workspace_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row



@router.patch("/{content_id}/node-type")
def set_node_type(content_id: str, req: NodeTypeRequest, auth: AuthContext = Depends(require_permission("content.update"))) -> dict:
    if req.node_type not in VALID_NODE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid node_type '{req.node_type}'. Must be one of: {', '.join(sorted(VALID_NODE_TYPES))}",
        )
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.set_node_type(content_id=content_id, node_type=req.node_type, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return {
        **row,
        "updated": True,
        "deterministic": True,
        "provider_backed": False,
        "classification_mode": "caller_specified",
        "allowed_node_types": sorted(VALID_NODE_TYPES),
    }
