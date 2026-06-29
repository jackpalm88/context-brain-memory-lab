from __future__ import annotations

import pytest

from memory_lab.query.ask_projection import (
    ask_confidence_for,
    citations_from_evidence,
    insufficient_evidence_response,
    successful_ask_response,
    unsupported_intent_response,
)
from memory_lab.reasoning.answer_synthesizer import _confidence_for, synthesize_answer
from memory_lab.reasoning.intent_detector import IntentDetection
from memory_lab.reasoning.models import AskRequest, AskResponse, Citation, Claim, EvidenceItem
from memory_lab.reasoning.policy_generator import ReasoningPolicy

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000933"


def _evidence(count: int = 2) -> list[EvidenceItem]:
    return [
        EvidenceItem(
            evidence_id=f"ev-{idx}",
            rank=idx,
            content_id=f"cid-{idx}",
            chunk_id=f"chk-{idx}",
            snippet=f"Evidence snippet {idx}.",
            score=0.9 - idx / 100,
            score_kind="distance",
            retrieval_path="content_chunk_workspace_scoped",
            source="unit-test",
            title=f"Title {idx}",
            metadata={"custom": idx},
        )
        for idx in range(1, count + 1)
    ]


def _policy(intent: str = "factual", min_evidence_items: int = 1) -> ReasoningPolicy:
    return ReasoningPolicy(
        intent=intent,
        top_k=5,
        require_citations=True,
        min_evidence_items=min_evidence_items,
        fallback_behavior="insufficient_evidence",
        insufficient_evidence_behavior="insufficient_workspace_evidence",
    )


def _legacy_confidence_for(evidence: list[EvidenceItem]) -> tuple[float, str]:
    if not evidence:
        return 0.0, "No workspace evidence was retrieved, so no factual confidence is assigned."
    if len(evidence) == 1:
        return 0.45, "Conservative deterministic confidence based on one workspace-scoped evidence item."
    return min(0.7, 0.5 + min(len(evidence), 4) * 0.05), "Conservative deterministic confidence based on multiple workspace-scoped evidence items."


def _legacy_success_response(
    *, intent: str, evidence: list[EvidenceItem], include_evidence: bool, workspace_id: str
) -> AskResponse:
    confidence, explanation = _legacy_confidence_for(evidence)
    citations = [
        Citation(evidence_id=e.evidence_id, rank=e.rank, content_id=e.content_id, chunk_id=e.chunk_id, score=e.score)
        for e in evidence
    ]
    snippets = [f"[{e.evidence_id}] {e.snippet}" for e in evidence]
    answer = "Based only on retrieved workspace evidence: " + " ".join(snippets)
    claims = [Claim(claim=e.snippet, evidence_ids=[e.evidence_id]) for e in evidence]
    return AskResponse(
        answer=answer,
        intent=intent,
        confidence=confidence,
        confidence_explanation=explanation,
        citations=citations,
        evidence=evidence if include_evidence else [],
        claims=claims,
        degraded=False,
        insufficient_evidence=False,
        workspace_id=workspace_id,
        status="ok",
        failure_reason=None,
    )


def _legacy_insufficient_response(
    *, intent: str, evidence: list[EvidenceItem], include_evidence: bool, workspace_id: str
) -> AskResponse:
    return AskResponse(
        answer="Insufficient workspace evidence was found to answer this question without introducing unsupported facts.",
        intent=intent,
        confidence=0.0,
        confidence_explanation="The retrieval step returned too little workspace-scoped evidence for this intent.",
        citations=[],
        evidence=evidence if include_evidence else [],
        claims=[],
        degraded=True,
        insufficient_evidence=True,
        workspace_id=workspace_id,
        status="insufficient_evidence",
        failure_reason="insufficient_workspace_evidence",
    )


def _legacy_unsupported_response(*, intent: str, workspace_id: str) -> AskResponse:
    return AskResponse(
        answer="I need a clearer question before I can search workspace evidence.",
        intent=intent,
        confidence=0.0,
        confidence_explanation="The query was empty or unsupported.",
        degraded=True,
        insufficient_evidence=True,
        workspace_id=workspace_id,
        status="unsupported_intent",
        failure_reason="unsupported_or_empty_query",
    )


def test_ask_confidence_helper_preserves_legacy_formula_and_alias():
    for count in range(0, 7):
        evidence = _evidence(count)
        expected = _legacy_confidence_for(evidence)
        assert ask_confidence_for(evidence) == expected
        assert _confidence_for(evidence) == expected


def test_citation_projection_preserves_legacy_evidence_item_semantics():
    evidence = _evidence(2)

    assert [c.model_dump() for c in citations_from_evidence(evidence)] == [
        {
            "evidence_id": "ev-1",
            "rank": 1,
            "content_id": "cid-1",
            "chunk_id": "chk-1",
            "score": 0.89,
        },
        {
            "evidence_id": "ev-2",
            "rank": 2,
            "content_id": "cid-2",
            "chunk_id": "chk-2",
            "score": 0.88,
        },
    ]


def test_successful_ask_projection_matches_legacy_inline_ask_response():
    evidence = _evidence(2)

    actual = successful_ask_response(intent="factual", evidence=evidence, include_evidence=True, workspace_id=WS)
    expected = _legacy_success_response(intent="factual", evidence=evidence, include_evidence=True, workspace_id=WS)

    assert actual.model_dump() == expected.model_dump()


def test_successful_ask_projection_preserves_include_evidence_false_behavior():
    evidence = _evidence(1)

    actual = successful_ask_response(intent="find", evidence=evidence, include_evidence=False, workspace_id=WS)
    expected = _legacy_success_response(intent="find", evidence=evidence, include_evidence=False, workspace_id=WS)

    assert actual.model_dump() == expected.model_dump()
    assert actual.evidence == []
    assert actual.citations
    assert actual.claims


def test_insufficient_and_unsupported_projection_match_legacy_inline_responses():
    evidence = _evidence(1)

    assert insufficient_evidence_response(
        intent="compare", evidence=evidence, include_evidence=True, workspace_id=WS
    ).model_dump() == _legacy_insufficient_response(
        intent="compare", evidence=evidence, include_evidence=True, workspace_id=WS
    ).model_dump()

    assert unsupported_intent_response(intent="unknown", workspace_id=WS).model_dump() == _legacy_unsupported_response(
        intent="unknown", workspace_id=WS
    ).model_dump()


def test_synthesize_answer_delegates_to_ask_projection_with_exact_legacy_response_shapes():
    evidence = _evidence(2)
    req = AskRequest(query="What is preserved?", include_evidence=True)
    detection = IntentDetection(intent="factual", confidence=0.7, matched_rule="question_shape")

    actual = synthesize_answer(req, detection, _policy(), evidence, WS)
    expected = _legacy_success_response(intent="factual", evidence=evidence, include_evidence=True, workspace_id=WS)

    assert actual.model_dump() == expected.model_dump()


def test_synthesize_answer_delegates_insufficient_and_unsupported_paths():
    insufficient_req = AskRequest(query="Compare A and B", include_evidence=False)
    insufficient_detection = IntentDetection(intent="compare", confidence=0.8, matched_rule="compare_terms")
    evidence = _evidence(1)

    actual_insufficient = synthesize_answer(
        insufficient_req, insufficient_detection, _policy(intent="compare", min_evidence_items=2), evidence, WS
    )
    expected_insufficient = _legacy_insufficient_response(
        intent="compare", evidence=evidence, include_evidence=False, workspace_id=WS
    )
    assert actual_insufficient.model_dump() == expected_insufficient.model_dump()

    unsupported_req = AskRequest(query="")
    unsupported_detection = IntentDetection(intent="unknown", confidence=0.0, matched_rule="empty")
    actual_unsupported = synthesize_answer(unsupported_req, unsupported_detection, _policy(intent="unknown"), [], WS)

    assert actual_unsupported.model_dump() == _legacy_unsupported_response(intent="unknown", workspace_id=WS).model_dump()
