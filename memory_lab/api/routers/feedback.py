"""
DX-2: POST /v1/retrieval/feedback — record a thumbs-up/down signal on a retrieved item.

Contract:
  Request:  { "content_id": "...", "signal": "up"|"down", "query_text"?: "...", "metadata"?: {} }
  Response: { "feedback_id": "...", "recorded": true }

Signals are stored in cb_retrieval_feedback (migration 036). No FK to content_items —
items may be pruned. feedback_id is returned for dedup / client tracking.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])

VALID_SIGNALS = frozenset({"up", "down"})


class FeedbackRequest(BaseModel):
    content_id: str
    signal: str  # "up" | "down"
    query_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/feedback", summary="Record a relevance signal on a retrieved content item")
def record_feedback(
    req: FeedbackRequest,
    auth: AuthContext = Depends(require_permission("retrieval.search")),
) -> dict:
    """Store a thumbs-up or thumbs-down signal for a retrieved content item.

    Signals feed into future ranking improvements. The endpoint is intentionally
    lightweight — no content_id validation, no dedup. Use the returned feedback_id
    for client-side dedup if needed.
    """
    if req.signal not in VALID_SIGNALS:
        raise HTTPException(status_code=422, detail=f"signal must be one of: {sorted(VALID_SIGNALS)}")

    settings = get_settings()
    import json

    with psycopg2.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            # Resolve workspace UUID
            workspace_uuid = None
            if auth.workspace_id:
                cur.execute(
                    "SELECT workspace_id FROM cb_workspaces WHERE workspace_id = %s",
                    (auth.workspace_id,),
                )
                row = cur.fetchone()
                workspace_uuid = row[0] if row else None

            cur.execute(
                """
                INSERT INTO cb_retrieval_feedback
                    (content_id, query_text, signal, workspace_id, subject_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING feedback_id
                """,
                (
                    req.content_id,
                    req.query_text,
                    req.signal,
                    workspace_uuid,
                    str(auth.auth_subject_id) if auth.auth_subject_id else None,
                    json.dumps(req.metadata or {}),
                ),
            )
            feedback_id = str(cur.fetchone()[0])
        conn.commit()

    return {"feedback_id": feedback_id, "recorded": True}
