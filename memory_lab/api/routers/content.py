from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend

router = APIRouter(prefix="/v1/content", tags=["content"])


class ContentCreateRequest(BaseModel):
    content: Optional[str] = None
    workspace_id: Optional[str] = None
    scope_hint: Optional[str] = Field(None, max_length=120, description=(
        "Explicit current-state scope key for this content item. "
        "When supplied it bypasses heuristic keyword matching and is slugified "
        "directly into current_state_scope. Prevents unrelated items in the same "
        "workspace from collapsing into the 'global' scope and silently superseding "
        "each other."
    ))


class QuickSummaryRequest(BaseModel):
    quick_summary: str = Field(..., max_length=500)


VALID_NODE_TYPES = frozenset({
    "decision", "fact", "hypothesis", "question", "playbook",
    "concept", "source", "task", "event", "raw_note",
})


class NodeTypeRequest(BaseModel):
    node_type: str


def _make_embedding_backend(settings):
    """Return a configured OpenAIEmbeddingBackend when provider embeddings are enabled,
    else None. Graceful: returns None (not raises) when provider is absent or not configured.
    Uses getattr defensively so minimal/mock settings objects without the attribute default to off."""
    if not getattr(settings, "provider_embeddings_enabled", False):
        return None
    try:
        backend = OpenAIEmbeddingBackend()
        return backend  # is_configured checked per-call inside persist_body_chunks
    except Exception:
        return None


# EB-2: an empty save must fail loudly, never return persisted=true. Before this
# guard, a missing/empty body deduplicated onto a shared empty content item.
EMPTY_CONTENT_DETAIL = "content is required and must be non-empty"


@router.post("")
def create_content(req: ContentCreateRequest, auth: AuthContext = Depends(require_permission("content.create"))) -> dict:
    if req.content is None or not req.content.strip():
        raise HTTPException(status_code=422, detail=EMPTY_CONTENT_DETAIL)
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url, embedding_backend=_make_embedding_backend(settings))
    return adapter.create_content_minimal(
        content=req.content,
        workspace_id=auth.workspace_id,
        workspace_source=auth.workspace_source,
        created_by_subject=auth.auth_subject_id,
        scope_hint=req.scope_hint,
    )


@router.get("/{content_id}")
def get_content(content_id: str, auth: AuthContext = Depends(require_permission("content.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_minimal(content_id, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row


@router.get("/{content_id}/metadata")
def get_content_metadata(content_id: str, auth: AuthContext = Depends(require_permission("content.read"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_content_metadata(content_id, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row


@router.get("/{content_id}/canonical-body")
def get_canonical_body(
    content_id: str,
    expected_version: Optional[str] = Query(None, min_length=1),
    auth: AuthContext = Depends(require_permission("content.read")),
) -> dict:
    """Read-only, additive (Patch 1 / OpenCB decision 5533831e-c751-434a-8ae7-f8f40cdaf0f8;
    expected_version added in Patch 1.1 / decision b97a9f74-2d8c-4427-af46-4780aa9ce986).

    `body` is populated only when `fidelity` is `hash-verified`; otherwise it
    is null (`unverifiable` or `unavailable`) -- this endpoint never claims
    exact body fidelity it has not proven with a SHA-256 match against the
    stored content_hash.

    expected_version, when supplied, is checked against the stored
    content_hash before any reconstruction is attempted: a match proceeds
    normally, a mismatch or an unknown-version content item returns 409
    (never a guessed body), checked before the 200/null-body path.
    """
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.get_canonical_body(
        content_id, workspace_id=auth.workspace_id, expected_version=expected_version
    )
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    if row.get("version_conflict"):
        raise HTTPException(
            status_code=409,
            detail={
                "detail": row["reason"],  # "mismatch" | "version_unknown"
                "expected_version": row["expected_version"],
                "current_version": row["current_version"],
            },
        )
    row.pop("version_conflict", None)
    return row


@router.patch("/{content_id}/quick-summary")
def set_quick_summary(content_id: str, req: QuickSummaryRequest, auth: AuthContext = Depends(require_permission("content.update"))) -> dict:
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.set_quick_summary(
        content_id=content_id,
        quick_summary=req.quick_summary,
        workspace_id=auth.workspace_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return row



@router.patch("/{content_id}/node-type")
def set_node_type(content_id: str, req: NodeTypeRequest, auth: AuthContext = Depends(require_permission("content.update"))) -> dict:
    if req.node_type not in VALID_NODE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid node_type '{req.node_type}'. Must be one of: {', '.join(sorted(VALID_NODE_TYPES))}",
        )
    settings = get_settings()
    adapter = ApiAdapter(settings.database_url)
    row = adapter.set_node_type(content_id=content_id, node_type=req.node_type, workspace_id=auth.workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="content not found")
    return {
        **row,
        "updated": True,
        "deterministic": True,
        "provider_backed": False,
        "classification_mode": "caller_specified",
        "allowed_node_types": sorted(VALID_NODE_TYPES),
    }
