from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/content", tags=["content"])


class ContentCreateRequest(BaseModel):
    content: Optional[str] = None
    workspace_id: Optional[str] = None


@router.post("")
def create_content(req: ContentCreateRequest, auth: AuthContext = Depends(require_permission("content.create"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_content_minimal(
        content=req.content,
        workspace_id=auth.workspace_id,
        workspace_source=auth.workspace_source,
    )


@router.get("/{content_id}")
def get_content(content_id: str, auth: AuthContext = Depends(require_permission("content.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_minimal(content_id, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row
