from fastapi import APIRouter, Depends, HTTPException

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.reasoning.models import ReasoningRequest
from memory_lab.reasoning.service import explain_for_request, traverse_for_request

router = APIRouter(prefix="/v1/reasoning", tags=["reasoning"])


def _check_workspace(req: ReasoningRequest, auth: AuthContext) -> None:
    if req.workspace_id and req.workspace_id != auth.workspace_id:
        raise HTTPException(status_code=403, detail="workspace_id_mismatch")


@router.post("/traverse")
def traverse(req: ReasoningRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> dict:
    _check_workspace(req, auth)
    settings = get_settings()
    response = traverse_for_request(
        database_url=settings.database_url,
        request=req,
        workspace_id=auth.workspace_id,
        workspace_source=auth.workspace_source,
    )
    return response.model_dump()


@router.post("/explain")
def explain(req: ReasoningRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> dict:
    _check_workspace(req, auth)
    settings = get_settings()
    response = explain_for_request(
        database_url=settings.database_url,
        request=req,
        workspace_id=auth.workspace_id,
        workspace_source=auth.workspace_source,
    )
    return response.model_dump()
