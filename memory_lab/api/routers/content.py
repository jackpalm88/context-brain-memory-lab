from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from memory_lab.api.config import get_settings
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.api.workspace_context import WorkspaceContext, get_workspace_context

router = APIRouter(prefix="/v1/content", tags=["content"])


class ContentCreateRequest(BaseModel):
    content: Optional[str] = None
    workspace_id: Optional[str] = None


@router.post("")
def create_content(req: ContentCreateRequest, workspace: WorkspaceContext = Depends(get_workspace_context)) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_content_minimal(
        content=req.content,
        workspace_id=workspace.workspace_id,
        workspace_source=workspace.source,
    )


@router.get("/{content_id}")
def get_content(content_id: str, workspace: WorkspaceContext = Depends(get_workspace_context)) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_minimal(content_id, workspace_id=workspace.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row
