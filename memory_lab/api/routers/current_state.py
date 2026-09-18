"""CF-003: readable current-state anchors.

The resolver has always WRITTEN cb_current_state_anchors; nothing public could
READ it, so consumers needing "the current item of scope S" (e.g. the successor
of a superseded item) had to probe retrieval results and hope the successor was
ranked. This router is the forward pointer: given a scope, return its active
anchor(s).

Phase A (decision 4a11008b): `scope` is a grouping query and may legitimately
return multiple active anchors per memory_type — one per distinct
state_identity. Pass state_identity too to narrow to the one current item for a
specific tracked fact.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.current_state.scope_pipeline import _slugify_scope
from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES


class TrustedCurrentStatePromotionRequest(BaseModel):
    content: str = Field(..., min_length=1)
    memory_type: str = Field(..., description="Explicit memory_type component of the replacement identity key.")
    state_identity: str = Field(..., min_length=1, max_length=200, description="Explicit replacement identity; never inferred by this endpoint.")
    scope_hint: Optional[str] = Field(None, max_length=120, description="Grouping/readback scope. Defaults to state_identity when omitted.")
    quick_summary: Optional[str] = Field(None, max_length=500)


def _assert_trusted_promoter(auth: AuthContext) -> None:
    # Defense-in-depth beyond RBAC: this seam is for allowlisted trusted callers,
    # not ordinary writer/content.create callers. The default trusted set matches
    # deployment reality (owner/admin service operators plus service agents) and
    # can be narrowed by env without changing code.
    import os
    allowed = {r.strip() for r in os.environ.get("MEMORY_LAB_TRUSTED_CURRENT_STATE_PROMOTION_ROLES", "owner,admin,service_agent").split(",") if r.strip()}
    if auth.role not in allowed:
        raise HTTPException(status_code=403, detail="trusted_current_state_promoter_required")

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
        "active anchor per memory type per distinct state_identity that has one "
        "(plus at most one legacy, pre-Phase-A anchor with no state_identity)."
    )),
    state_identity: Optional[str] = Query(None, max_length=200, description=(
        "Optional filter to the one active anchor for a specific tracked fact. "
        "Required if you want a single current item rather than the full set of "
        "everything active under this scope."
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
        state_identity=state_identity,
    )
    return {
        "anchors": anchors,
        "count": len(anchors),
        "scope": normalized_scope,
        "workspace_id": auth.workspace_id,
    }


@router.post("/promote")
def trusted_promote_current_state(
    req: TrustedCurrentStatePromotionRequest,
    auth: AuthContext = Depends(require_permission("current_state.promote")),
) -> dict:
    """Trusted current-state promotion seam.

    General /v1/content remains intentionally unable to accept state_identity.
    This endpoint is the narrow allowlisted authority path for canonical state: it
    requires explicit memory_type + state_identity and supersedes only within
    (workspace_id, memory_type, state_identity). Rollback is performed by another
    trusted write that restores the prior semantic state.
    """
    _assert_trusted_promoter(auth)
    if req.memory_type not in MEMORY_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown memory_type '{req.memory_type}'. Allowed: {', '.join(sorted(MEMORY_TYPE_VALUES))}",
        )
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    try:
        return adapter.trusted_promote_current_state(
            content=req.content,
            workspace_id=auth.workspace_id,
            workspace_source=auth.workspace_source,
            created_by_subject=auth.auth_subject_id,
            memory_type=req.memory_type,
            state_identity=req.state_identity,
            scope_hint=req.scope_hint,
            quick_summary=req.quick_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
