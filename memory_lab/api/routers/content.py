from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memory_lab.api.config import get_settings
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/content", tags=["content"])


class ContentCreateRequest(BaseModel):
    content: Optional[str] = None


@router.post("")
def create_content(req: ContentCreateRequest) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    return adapter.create_content_minimal(content=req.content)


@router.get("/{content_id}")
def get_content(content_id: str) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_minimal(content_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row
