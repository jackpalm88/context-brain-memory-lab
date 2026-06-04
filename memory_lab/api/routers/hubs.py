from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from memory_lab.api.config import get_settings
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.api.workspace_context import WorkspaceContext, get_workspace_context

router = APIRouter(prefix="/v1/hubs", tags=["hubs"])


class HubCreateRequest(BaseModel):
    title: str
    hub_type: Optional[str] = "topic"
    description: Optional[str] = None
    aliases: Optional[List[str]] = None
    related_terms: Optional[List[str]] = None
    workspace_id: Optional[str] = None


class HubLinkRequest(BaseModel):
    content_id: str


@router.post("")
def create_hub(req: HubCreateRequest, workspace: WorkspaceContext = Depends(get_workspace_context)) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_hub(req.model_dump(), workspace_id=workspace.workspace_id, workspace_source=workspace.source)


@router.get("/{hub_id}")
def get_hub(hub_id: str, workspace: WorkspaceContext = Depends(get_workspace_context)) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    hub = adapter.get_hub(hub_id, workspace_id=workspace.workspace_id)
    if not hub:
        raise HTTPException(status_code=404, detail="hub not found")
    return hub


@router.post("/{hub_id}/links")
def link_content(hub_id: str, req: HubLinkRequest, workspace: WorkspaceContext = Depends(get_workspace_context)) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    try:
        return adapter.link_content(hub_id, req.content_id, workspace_id=workspace.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
