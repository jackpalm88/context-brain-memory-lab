from typing import List, Optional

import psycopg2
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.conflicts.service import search_conflict_candidates

router = APIRouter(prefix="/v1/conflicts", tags=["conflicts"])


class ConflictSearchRequest(BaseModel):
    query: Optional[str] = None
    scope: Optional[str] = None
    memory_type: Optional[str] = None
    memory_types: Optional[List[str]] = None
    include_resolved: bool = True
    limit: int = Field(default=10, ge=0, le=50)


@router.post("/search")
def conflicts_search(req: ConflictSearchRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> dict:
    settings = get_settings()
    with psycopg2.connect(settings.database_url) as conn:
        result = search_conflict_candidates(
            conn,
            workspace_id=auth.workspace_id,
            workspace_source=auth.workspace_source,
            query=req.query,
            scope=req.scope,
            memory_type=req.memory_type,
            memory_types=req.memory_types,
            include_resolved=req.include_resolved,
            limit=req.limit,
        )
    return result.model_dump()
