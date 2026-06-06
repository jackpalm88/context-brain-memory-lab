from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.reasoning.answer_synthesizer import normalize_evidence, synthesize_answer
from memory_lab.reasoning.intent_detector import detect_intent
from memory_lab.reasoning.models import AskRequest, AskResponse
from memory_lab.reasoning.policy_generator import policy_for_intent

router = APIRouter(prefix="/v1/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
def ask(req: AskRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> AskResponse:
    query = req.normalized_query()
    if not query:
        raise HTTPException(status_code=422, detail="query or question is required")

    detection = detect_intent(query)
    policy = policy_for_intent(detection.intent, req.top_k)
    settings = get_settings()
    adapter = RetrievalAdapter(settings.database_url)
    results = adapter.search(
        query=query,
        max_hops=1,
        min_confidence=0.0,
        graph_boost=0.1,
        workspace_id=auth.workspace_id,
    )
    evidence = normalize_evidence(results[: policy.top_k], limit=policy.snippet_char_limit)
    return synthesize_answer(
        request=req,
        detection=detection,
        policy=policy,
        evidence=evidence,
        workspace_id=auth.workspace_id,
    )
