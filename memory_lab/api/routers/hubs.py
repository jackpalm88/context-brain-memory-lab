from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.graph.hub_store import HubStore

router = APIRouter(prefix="/v1/hubs", tags=["hubs"])


class HubCreateRequest(BaseModel):
    title: str
    hub_type: Optional[str] = "topic"
    description: Optional[str] = None
    aliases: Optional[List[str]] = None
    related_terms: Optional[List[str]] = None


class HubUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    type: Optional[str] = Field(None, pattern="^(project|system|concept_cluster|topic)$")
    description: Optional[str] = None
    aliases: Optional[List[str]] = None
    related_terms: Optional[List[str]] = None
    status: Optional[str] = Field(None, pattern="^(active|archived)$")


class HubLinkRequest(BaseModel):
    content_id: str


class HubResponse(BaseModel):
    hub_id: str
    title: str
    type: str
    description: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    related_terms: List[str] = Field(default_factory=list)
    status: str
    owner_defined: bool
    workspace_uuid: Optional[str] = None
    linked_content_ids: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


@router.post("")
def create_hub(req: HubCreateRequest, auth: AuthContext = Depends(require_permission("hubs.create"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_hub(req.model_dump(), workspace_id=auth.workspace_id, workspace_source=auth.workspace_source)


@router.get("", response_model=List[HubResponse])
def list_hubs(
    status: str = "active",
    auth: AuthContext = Depends(require_permission("hubs.read")),
) -> List[HubResponse]:
    store = HubStore(get_settings().database_url)
    hubs = store.list_hubs(workspace_id=auth.workspace_id, status=status)
    for h in hubs:
        h.setdefault("linked_content_ids", [])
    return hubs


@router.get("/{hub_id}")
def get_hub(hub_id: str, auth: AuthContext = Depends(require_permission("hubs.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    hub = adapter.get_hub(hub_id, workspace_id=auth.workspace_id)
    if not hub:
        raise HTTPException(status_code=404, detail="hub not found")
    return hub


@router.patch("/{hub_id}", response_model=HubResponse)
def update_hub(
    hub_id: str,
    req: HubUpdateRequest,
    auth: AuthContext = Depends(require_permission("hubs.update")),
) -> HubResponse:
    store = HubStore(get_settings().database_url)
    updates = req.model_dump(exclude_none=True)
    hub = store.update_hub(hub_id, updates, workspace_id=auth.workspace_id)
    if not hub:
        raise HTTPException(status_code=404, detail="hub not found")
    hub.setdefault("linked_content_ids", [])
    return hub


@router.post("/{hub_id}/links")
def link_content(hub_id: str, req: HubLinkRequest, auth: AuthContext = Depends(require_permission("hubs.link"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    try:
        return adapter.link_content(hub_id, req.content_id, workspace_id=auth.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
