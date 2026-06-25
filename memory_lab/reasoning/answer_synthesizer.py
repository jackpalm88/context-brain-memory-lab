from __future__ import annotations

import re
from typing import Any

from .intent_detector import IntentDetection
from .models import AskRequest, AskResponse, Citation, Claim, EvidenceItem
from .policy_generator import ReasoningPolicy


def _clean_snippet(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _score_kind(retrieval_path: str) -> str:
    if "hub" in retrieval_path:
        return "hub_link"
    return "chunk_text_match"


PROVENANCE_METADATA_KEYS = (
    "retrieval_mode",
    "retrieval_path",
    "embedding_status",
    "distance",
    "score_kind",
)


def _provenance_metadata(row: dict[str, Any], *, retrieval_path: str, score_kind: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    existing = row.get("metadata")
    if isinstance(existing, dict):
        metadata.update({k: v for k, v in existing.items() if v is not None})
    enriched = dict(row)
    enriched.setdefault("retrieval_path", retrieval_path)
    enriched.setdefault("score_kind", score_kind)
    for key in PROVENANCE_METADATA_KEYS:
        value = enriched.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def normalize_evidence(results: list[dict[str, Any]], limit: int = 320) -> list[EvidenceItem]:
    """Map public RetrievalAdapter rows into stable, deduplicated evidence items."""
    evidence: list[EvidenceItem] = []
    seen_content_ids: set[str] = set()
    rank = 0
    for row in results:
        content_id = str(row.get("content_id") or row.get("id") or "").strip()
        text = str(row.get("text") or row.get("snippet") or "").strip()
        if not content_id or not text:
            continue
        if content_id in seen_content_ids:
            continue
        seen_content_ids.add(content_id)
        rank += 1
        chunk_id = row.get("chunk_id")
        chunk_id_str = str(chunk_id).strip() if chunk_id else None
        retrieval_path = str(row.get("retrieval_path") or "deterministic_db").strip()
        score_kind = str(row.get("score_kind") or _score_kind(retrieval_path)).strip()
        score = row.get("score")
        metadata = _provenance_metadata(row, retrieval_path=retrieval_path, score_kind=score_kind)
        if chunk_id_str:
            evidence_id = f"ev_{content_id}_{chunk_id_str}"
        else:
            evidence_id = f"ev_{content_id}_{retrieval_path}_{rank}"
        evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
                rank=rank,
                content_id=content_id,
                chunk_id=chunk_id_str,
                snippet=_clean_snippet(text, limit),
                score=float(score) if score is not None else None,
                score_kind=score_kind,
                retrieval_path=retrieval_path,
                source=row.get("source") or row.get("title"),
                title=row.get("title"),
                metadata=metadata or None,
            )
        )
    return evidence


def _confidence_for(evidence: list[EvidenceItem]) -> tuple[float, str]:
    if not evidence:
        return 0.0, "No workspace evidence was retrieved, so no factual confidence is assigned."
    if len(evidence) == 1:
        return 0.45, "Conservative deterministic confidence based on one workspace-scoped evidence item."
    return min(0.7, 0.5 + min(len(evidence), 4) * 0.05), "Conservative deterministic confidence based on multiple workspace-scoped evidence items."


def synthesize_answer(
    request: AskRequest,
    detection: IntentDetection,
    policy: ReasoningPolicy,
    evidence: list[EvidenceItem],
    workspace_id: str,
) -> AskResponse:
    """Deterministic/noop answer synthesis from evidence snippets only."""
    query = request.normalized_query()
    if detection.intent == "unknown" or not query:
        return AskResponse(
            answer="I need a clearer question before I can search workspace evidence.",
            intent=detection.intent,
            confidence=0.0,
            confidence_explanation="The query was empty or unsupported.",
            degraded=True,
            insufficient_evidence=True,
            workspace_id=workspace_id,
            status="unsupported_intent",
            failure_reason="unsupported_or_empty_query",
        )

    if len(evidence) < max(1, policy.min_evidence_items):
        return AskResponse(
            answer="Insufficient workspace evidence was found to answer this question without introducing unsupported facts.",
            intent=detection.intent,
            confidence=0.0,
            confidence_explanation="The retrieval step returned too little workspace-scoped evidence for this intent.",
            citations=[],
            evidence=evidence if request.include_evidence else [],
            claims=[],
            degraded=True,
            insufficient_evidence=True,
            workspace_id=workspace_id,
            status="insufficient_evidence",
            failure_reason="insufficient_workspace_evidence",
        )

    confidence, explanation = _confidence_for(evidence)
    citations = [
        Citation(evidence_id=e.evidence_id, rank=e.rank, content_id=e.content_id, chunk_id=e.chunk_id, score=e.score)
        for e in evidence
    ]
    snippets = [f"[{e.evidence_id}] {e.snippet}" for e in evidence]
    answer = "Based only on retrieved workspace evidence: " + " ".join(snippets)
    claims = [Claim(claim=e.snippet, evidence_ids=[e.evidence_id]) for e in evidence]
    return AskResponse(
        answer=answer,
        intent=detection.intent,
        confidence=confidence,
        confidence_explanation=explanation,
        citations=citations,
        evidence=evidence if request.include_evidence else [],
        claims=claims,
        degraded=False,
        insufficient_evidence=False,
        workspace_id=workspace_id,
        status="ok",
        failure_reason=None,
    )
