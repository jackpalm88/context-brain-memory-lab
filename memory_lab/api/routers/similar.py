"""
DX-2: POST /v1/retrieval/similar — find content similar to a known content_id.

Contract:
  Request:  { "content_id": "...", "limit"?: 10 }
  Response: { "source_content_id": "...", "results": [...], "count": N }

Workspace comes from the auth context only — a body-supplied workspace is not
accepted (same posture as POST /v1/content and /v1/retrieval/search).

Fetches the stored chunk text for the given content_id, then runs a retrieval
search using that text as the query. Excludes the source item from results.
Returns 404 if content_id is not found in the workspace.
"""
from __future__ import annotations

import psycopg2
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
_QUERY_TEXT_CAP = 2000  # retrieval only consumes leading terms; cap the query size
_SOURCE_CHUNKS = 3      # leading chunks are enough signal for a similarity query


class SimilarRequest(BaseModel):
    content_id: str
    limit: int = Field(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX)


def _make_embedding_backend(settings):
    if not getattr(settings, "provider_embeddings_enabled", False):
        return None
    try:
        return OpenAIEmbeddingBackend()
    except Exception:
        return None


def _fetch_source_text(database_url: str, content_id: str, workspace_id: str) -> str:
    """Return the leading chunk text for a content row (workspace-scoped).

    content_items carries no body column — persisted text lives in
    content_chunks (EMB-1B multi-chunk save path).
    """
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ch.chunk_text
                  FROM content_chunks ch
                  JOIN content_items c ON c.content_id = ch.content_id
                 WHERE c.content_id = %s::uuid
                   AND c.workspace_id = %s::uuid
                   AND ch.chunk_text IS NOT NULL
                 ORDER BY ch.chunk_index ASC
                 LIMIT %s
                """,
                (content_id, workspace_id, _SOURCE_CHUNKS),
            )
            rows = cur.fetchall()
    return " ".join(r[0] for r in rows).strip()[:_QUERY_TEXT_CAP]


@router.post("/similar", summary="Find content similar to a given content_id")
def find_similar(
    req: SimilarRequest,
    auth: AuthContext = Depends(require_permission("retrieval.search")),
) -> dict:
    """Return content items most similar to the specified content_id.

    Retrieves the source item's chunk text, runs it through the standard
    retrieval pipeline, and returns ranked results excluding the source itself.
    """
    settings = get_settings()
    emb_backend = _make_embedding_backend(settings)
    workspace_id = auth.workspace_id

    # 404 before anything else: the source must exist in the caller's workspace.
    adapter = ApiAdapter(settings.database_url, embedding_backend=emb_backend)
    source = adapter.get_content_minimal(req.content_id, workspace_id=workspace_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"content_id {req.content_id!r} not found")

    query_text = _fetch_source_text(settings.database_url, req.content_id, workspace_id)
    if not query_text:
        raise HTTPException(status_code=422, detail="source content has no text to search with")

    retrieval = RetrievalAdapter(settings.database_url, embedding_backend=emb_backend)
    raw = retrieval.search(query=query_text, workspace_id=workspace_id)

    results = [r for r in raw if r.get("content_id") != req.content_id][: req.limit]

    return {
        "source_content_id": req.content_id,
        "results": results,
        "count": len(results),
    }
