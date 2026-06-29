from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.query.service import QueryService
from memory_lab.reasoning.models import AskRequest, AskResponse

router = APIRouter(prefix="/v1/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
def ask(req: AskRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> AskResponse:
    query = req.normalized_query()
    if not query:
        raise HTTPException(status_code=422, detail="query or question is required")

    settings = get_settings()
    service = QueryService.from_database_url(settings.database_url)
    return service.execute(req, workspace_id=auth.workspace_id)
