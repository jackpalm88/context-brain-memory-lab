"""
DX-2: POST /v1/retrieval/similar — find content similar to a known content_id.

Contract:
  Request:  { "content_id": "...", "workspace_id"?: "...", "limit"?: 10 }
  Response: { "source_content_id": "...", "results": [...], "count": N }

Fetches the stored chunk text for the given content_id, then runs a retrieval
search using that text as the query. Excludes the source item from results.
Returns 404 if content_id is not found in the workspace.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])

_LIMIT_MAX = 50
_LIMIT_DEFAULT = 10


class SimilarRequest(BaseModel):
    content_id: str
    workspace_id: Optional[str] = None
    limit: int = Field(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX)


def _make_embedding_backend(settings):
    if not getattr(settings, "provider_embeddings_enabled", False):
        return None
    try:
        return OpenAIEmbeddingBackend()
    except Exception:
        return None


@router.post("/similar", summary="Find content similar to a given content_id")
def find_similar(
    req: SimilarRequest,
    auth: AuthContext = Depends(require_permission("retrieval.search")),
) -> dict:
    """Return content items most similar to the specified content_id.

    Retrieves the source item's text, runs it through the standard retrieval
    pipeline, and returns ranked results excluding the source item itself.
    """
    settings = get_settings()
    emb_backend = _make_embedding_backend(settings)
    workspace_id = req.workspace_id or auth.workspace_id

    # Fetch source content
    adapter = ApiAdapter(settings.database_url, embedding_backend=emb_backend)
    source = adapter.get_content_minimal(req.content_id, workspace_id=workspace_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"content_id {req.content_id!r} not found")

    query_text = source.get("full_text") or source.get("content") or ""
    if not query_text.strip():
        raise HTTPException(status_code=422, detail="source content has no text to search with")

    # Run retrieval
    retrieval = RetrievalAdapter(settings.database_url, embedding_backend=emb_backend)
    raw = retrieval.search(
        query=query_text,
        workspace_id=workspace_id,
        limit=req.limit + 1,  # +1 so we can exclude source without underdelivering
    )

    # Exclude source item itself
    results = [r for r in raw if r.get("content_id") != req.content_id][: req.limit]

    return {
        "source_content_id": req.content_id,
        "results": results,
        "count": len(results),
    }
