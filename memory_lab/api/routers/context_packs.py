from fastapi import APIRouter, Depends, HTTPException

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.context_packs.service import build_context_pack_for_request

router = APIRouter(prefix="/v1/context-packs", tags=["context-packs"])


@router.post("/build")
def build_context_pack(req: ContextPackBuildRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> dict:
    if req.workspace_id and req.workspace_id != auth.workspace_id:
        raise HTTPException(status_code=403, detail="workspace_id_mismatch")
    settings = get_settings()
    response = build_context_pack_for_request(
        database_url=settings.database_url,
        request=req,
        workspace_id=auth.workspace_id,
        workspace_source=auth.workspace_source,
    )
    return response.model_dump()
