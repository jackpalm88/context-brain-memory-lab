"""
DX-2: POST /v1/content/batch — save multiple content items in one call.

Contract:
  Request:  { "items": [ {content, workspace_id?, save_purpose?}, ... ] }  max 50 items
  Response: { "results": [...], "summary": {total, persisted, deduplicated, discarded, failed} }

Each item goes through the same create_content_minimal path as POST /v1/content.
Items are processed sequentially (no DB transaction spanning all items — each is atomic).
Failed items are captured with error detail and do not abort the batch.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend

router = APIRouter(prefix="/v1/content", tags=["content"])

_BATCH_MAX = 50


class BatchItem(BaseModel):
    content: Optional[str] = None
    workspace_id: Optional[str] = None
    save_purpose: Optional[str] = None


class BatchRequest(BaseModel):
    items: List[BatchItem] = Field(..., min_length=1, max_length=_BATCH_MAX)


def _make_embedding_backend(settings):
    if not getattr(settings, "provider_embeddings_enabled", False):
        return None
    try:
        return OpenAIEmbeddingBackend()
    except Exception:
        return None


@router.post("/batch", summary="Save multiple content items in one request")
def batch_create(
    req: BatchRequest,
    auth: AuthContext = Depends(require_permission("content.create")),
) -> dict:
    """Save up to 50 content items in a single API call.

    Each item is processed independently through the standard save pipeline
    (dedup, scoring, tier routing). Failures on individual items are captured
    and returned inline — they do not abort the batch.
    """
    settings = get_settings()
    emb_backend = _make_embedding_backend(settings)
    adapter = ApiAdapter(settings.database_url, embedding_backend=emb_backend)

    results = []
    summary = {"total": len(req.items), "persisted": 0, "deduplicated": 0, "discarded": 0, "failed": 0}

    for idx, item in enumerate(req.items):
        try:
            result = adapter.create_content_minimal(
                content=item.content,
                workspace_id=item.workspace_id or auth.workspace_id,
            )
            results.append({"index": idx, "ok": True, **result})
            if result.get("duplicate"):
                summary["deduplicated"] += 1
            elif result.get("persisted"):
                summary["persisted"] += 1
            else:
                summary["discarded"] += 1
        except Exception as exc:
            results.append({"index": idx, "ok": False, "error": str(exc)})
            summary["failed"] += 1

    return {"results": results, "summary": summary}
