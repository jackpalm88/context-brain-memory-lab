from __future__ import annotations

import pytest

from memory_lab.query.context_pack_adapter import (
    build_support_only_context_pack_for_ask,
    evidence_items_from_supporting_context_pack,
)
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


def _row(content_id: str, chunk_id: str, text: str, score: float = 0.9, **extra) -> dict:
    row = {
        "content_id": content_id,
        "chunk_id": chunk_id,
        "text": text,
        "score": score,
        "retrieval_path": "content_chunk_workspace_scoped",
    }
    row.update(extra)
    return row


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
            "memory_types": None,
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


def test_query_service_rejects_vector_noise_without_query_overlap():
    rows = [
        _row(
            "cid-notification",
            "chk-notification",
            "decision: switch the notification transport to WebSockets.",
            retrieval_path="pgvector_knn",
            retrieval_mode="pgvector_knn",
        )
    ]
    req = AskRequest(query="What do we know about the payments retry queue?", top_k=5)
    adapter = FakeRetrievalAdapter(rows)

    response = QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)

    assert response.status == "insufficient_evidence"
    assert response.insufficient_evidence is True
    assert response.evidence == []


def test_support_only_context_pack_adapter_round_trips_evidence_item_exactly():
    rows = [
        _row(
            "cid-rich",
            "chk-rich",
            "Rich evidence preserves every public ask field through the internal context pack seam.",
            score=0.77,
            score_kind="chunk_text_match",
            source="source-name",
            title="Evidence title",
            metadata={"custom": "value", "distance": 0.23},
            retrieval_mode="hybrid",
            embedding_status="ok",
        )
    ]
    req = AskRequest(query="rich evidence", top_k=5)
    evidence = normalize_evidence(rows)

    context_pack = build_support_only_context_pack_for_ask(
        request=req,
        workspace_id=WS,
        query=req.normalized_query(),
        evidence=evidence,
        limit=5,
    )
    projected = evidence_items_from_supporting_context_pack(context_pack)

    assert [item.model_dump() for item in projected] == [item.model_dump() for item in evidence]
    assert context_pack.summary_metadata.include_flags == {
        "include_supporting_evidence": True,
        "include_current_state": False,
        "include_conflicts": False,
        "include_counterfindings": False,
    }
    assert context_pack.current_state_signals == []
    assert context_pack.conflict_candidates == []
    assert context_pack.counterfindings == []
    assert context_pack.stale_or_superseded_items == []


def test_query_service_context_pack_seam_preserves_rich_ask_response_exactly():
    rows = [
        _row(
            "cid-rich",
            "chk-rich",
            "The support-only context pack seam must not change public ask behavior.",
            score=0.77,
            score_kind="chunk_text_match",
            source="source-name",
            title="Evidence title",
            metadata={"custom": "value", "distance": 0.23},
            retrieval_mode="hybrid",
            embedding_status="ok",
        ),
        _row("cid-2", "chk-2", "Second item keeps rank and citation semantics stable.", score=0.66),
    ]
    req = AskRequest(query="What must stay stable?", top_k=5)
    adapter = FakeRetrievalAdapter(rows)

    actual = QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)
    expected = _previous_inline_ask_response(req, rows)

    assert actual.model_dump() == expected.model_dump()


def test_query_service_public_ask_response_does_not_leak_context_pack_internals():
    rows = [_row("cid-1", "chk-1", "Public ask response should not expose context pack internals.")]
    req = AskRequest(query="leak check", top_k=3)

    response = QueryService(retrieval_adapter=FakeRetrievalAdapter(rows)).execute(req, workspace_id=WS)
    body = response.model_dump()

    forbidden = {
        "context_pack_id",
        "context_pack_ref",
        "answer_candidate",
        "traversal_steps",
        "provider_metadata",
        "evidence_refs",
        "current_state_signals",
        "conflict_candidates",
        "counterfindings",
        "stale_or_superseded_items",
        "warnings",
        "non_claims",
    }
    assert forbidden.isdisjoint(body)
    assert set(body) == {
        "answer",
        "intent",
        "confidence",
        "confidence_explanation",
        "citations",
        "evidence",
        "claims",
        "degraded",
        "insufficient_evidence",
        "workspace_id",
        "status",
        "failure_reason",
        "mode",
    }
