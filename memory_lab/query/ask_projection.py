from __future__ import annotations

from memory_lab.reasoning.models import AskResponse, Citation, Claim, EvidenceItem


def ask_confidence_for(evidence: list[EvidenceItem]) -> tuple[float, str]:
    """Return the existing deterministic ask confidence for retrieved evidence.

    This helper intentionally preserves the public /v1/ask confidence formula:
    confidence is based only on filtered workspace evidence count, not provider,
    retrieval, validation, or reasoning confidence.
    """
    if not evidence:
        return 0.0, "No workspace evidence was retrieved, so no factual confidence is assigned."
    if len(evidence) == 1:
        return 0.45, "Conservative deterministic confidence based on one workspace-scoped evidence item."
    return min(0.7, 0.5 + min(len(evidence), 4) * 0.05), "Conservative deterministic confidence based on multiple workspace-scoped evidence items."


def citations_from_evidence(evidence: list[EvidenceItem]) -> list[Citation]:
    """Project EvidenceItem values to the existing public ask Citation shape."""
    return [
        Citation(evidence_id=e.evidence_id, rank=e.rank, content_id=e.content_id, chunk_id=e.chunk_id, score=e.score)
        for e in evidence
    ]


def answer_text_from_evidence(evidence: list[EvidenceItem]) -> str:
    """Build the existing deterministic ask answer text from evidence snippets."""
    snippets = [f"[{e.evidence_id}] {e.snippet}" for e in evidence]
    return "Based only on retrieved workspace evidence: " + " ".join(snippets)


def claims_from_evidence(evidence: list[EvidenceItem]) -> list[Claim]:
    """Project evidence snippets to the existing public ask Claim shape."""
    return [Claim(claim=e.snippet, evidence_ids=[e.evidence_id]) for e in evidence]


def unsupported_intent_response(*, intent: str, workspace_id: str) -> AskResponse:
    """Return the existing unsupported/empty query AskResponse."""
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


def insufficient_evidence_response(
    *,
    intent: str,
    evidence: list[EvidenceItem],
    include_evidence: bool,
    workspace_id: str,
) -> AskResponse:
    """Return the existing insufficient-evidence AskResponse."""
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


def successful_ask_response(
    *,
    intent: str,
    evidence: list[EvidenceItem],
    include_evidence: bool,
    workspace_id: str,
) -> AskResponse:
    """Return the existing successful public AskResponse projection."""
    confidence, explanation = ask_confidence_for(evidence)
    return AskResponse(
        answer=answer_text_from_evidence(evidence),
        intent=intent,
        confidence=confidence,
        confidence_explanation=explanation,
        citations=citations_from_evidence(evidence),
        evidence=evidence if include_evidence else [],
        claims=claims_from_evidence(evidence),
        degraded=False,
        insufficient_evidence=False,
        workspace_id=workspace_id,
        status="ok",
        failure_reason=None,
    )
