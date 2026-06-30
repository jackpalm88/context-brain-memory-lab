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
    backend = None
    if settings.ask_provider_synthesis_enabled:
        # Resolve a configured LLM backend (Anthropic if keyed, else Noop) only when the
        # deployment gate is on. The per-request opt-in is enforced inside the provider gate.
        from memory_lab.reasoning.service import get_reasoning_llm_backend

        backend = get_reasoning_llm_backend()
    service = QueryService.from_database_url(
        settings.database_url,
        provider_synthesis_enabled=settings.ask_provider_synthesis_enabled,
        backend=backend,
    )
    return service.execute(req, workspace_id=auth.workspace_id)
