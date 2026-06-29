from __future__ import annotations

import pytest

from memory_lab.query.evidence import normalize_evidence
from memory_lab.query.service import QueryService
from memory_lab.reasoning.answer_synthesizer import synthesize_answer
from memory_lab.reasoning.intent_detector import detect_intent
from memory_lab.reasoning.models import AskRequest
from memory_lab.reasoning.policy_generator import policy_for_intent

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000933"


class FakeRetrievalAdapter:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.rows)


def _row(content_id: str, chunk_id: str, text: str, score: float = 0.9) -> dict:
    return {
        "content_id": content_id,
        "chunk_id": chunk_id,
        "text": text,
        "score": score,
        "retrieval_path": "content_chunk_workspace_scoped",
    }


def _previous_inline_ask_response(req: AskRequest, rows: list[dict]):
    query = req.normalized_query()
    detection = detect_intent(query)
    policy = policy_for_intent(detection.intent, req.top_k)
    evidence = normalize_evidence(rows[: policy.top_k], limit=policy.snippet_char_limit)
    return synthesize_answer(
        request=req,
        detection=detection,
        policy=policy,
        evidence=evidence,
        workspace_id=WS,
    )


def test_query_service_matches_previous_inline_ask_orchestration():
    rows = [
        _row("cid-1", "chk-1", "The canonical query service preserves existing ask behavior."),
        _row("cid-2", "chk-2", "The router should become a thin adapter only.", score=0.8),
    ]
    req = AskRequest(query="What does the canonical query service preserve?", top_k=5)
    adapter = FakeRetrievalAdapter(rows)

    actual = QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)
    expected = _previous_inline_ask_response(req, rows)

    assert actual.model_dump() == expected.model_dump()


def test_query_service_preserves_retrieval_kwargs():
    rows = [_row("cid-1", "chk-1", "Find this exact thing.")]
    req = AskRequest(query="find exact thing", top_k=3)
    adapter = FakeRetrievalAdapter(rows)

    QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)

    assert adapter.calls == [
        {
            "query": "find exact thing",
            "max_hops": 1,
            "min_confidence": 0.0,
            "graph_boost": 0.1,
            "workspace_id": WS,
        }
    ]


def test_query_service_preserves_degraded_no_evidence_behavior():
    req = AskRequest(query="What evidence is available?", top_k=5)
    adapter = FakeRetrievalAdapter([])

    response = QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)

    assert response.status == "insufficient_evidence"
    assert response.degraded is True
    assert response.insufficient_evidence is True
    assert response.confidence == 0.0
    assert response.citations == []
    assert response.evidence == []
    assert response.workspace_id == WS
