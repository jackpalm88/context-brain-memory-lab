from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memory_lab.api.config import get_settings
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/hubs", tags=["hubs"])


class HubCreateRequest(BaseModel):
    title: str
    hub_type: Optional[str] = "topic"
    description: Optional[str] = None
    aliases: Optional[List[str]] = None
    related_terms: Optional[List[str]] = None


class HubLinkRequest(BaseModel):
    content_id: str


@router.post("")
def create_hub(req: HubCreateRequest) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_hub(req.model_dump())


@router.get("/{hub_id}")
def get_hub(hub_id: str) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    hub = adapter.get_hub(hub_id)
    if not hub:
        raise HTTPException(status_code=404, detail="hub not found")
    return hub


@router.post("/{hub_id}/links")
def link_content(hub_id: str, req: HubLinkRequest) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.link_content(hub_id, req.content_id)
