"""CF-003: readable current-state anchors.

The resolver has always WRITTEN cb_current_state_anchors; nothing public could
READ it, so consumers needing "the current item of scope S" (e.g. the successor
of a superseded item) had to probe retrieval results and hope the successor was
ranked. This router is the forward pointer: given a scope, return its active
anchor(s) — at most one per memory_type by resolver invariant.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.current_state.scope_pipeline import _slugify_scope
from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES

router = APIRouter(prefix="/v1/current-state", tags=["current-state"])


@router.get("/anchors")
def list_current_state_anchors(
    scope: str = Query(..., min_length=1, max_length=200, description=(
        "Current-state scope key. Normalized with the same slugifier the write "
        "path uses, so raw scope hints (e.g. 'Kafka choice') match their stored "
        "form ('kafka-choice'). The response reports the normalized scope queried."
    )),
    memory_type: Optional[str] = Query(None, description=(
        "Optional filter to one memory type; without it the scope returns one "
        "active anchor per memory type that has one."
    )),
    auth: AuthContext = Depends(require_permission("content.read")),
) -> dict:
    if memory_type is not None and memory_type not in MEMORY_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown memory_type '{memory_type}'. Allowed: {', '.join(sorted(MEMORY_TYPE_VALUES))}",
        )
    normalized_scope = _slugify_scope(scope)
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    anchors = adapter.list_current_state_anchors(
        scope=normalized_scope,
        memory_type=memory_type,
        workspace_id=auth.workspace_id,
    )
    return {
        "anchors": anchors,
        "count": len(anchors),
        "scope": normalized_scope,
        "workspace_id": auth.workspace_id,
    }
