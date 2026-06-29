from __future__ import annotations

from .intent_detector import IntentDetection
from .models import AskRequest, AskResponse, EvidenceItem
from .policy_generator import ReasoningPolicy

# normalize_evidence now lives in the neutral canonical query/evidence layer.
# Re-exported here so existing callers importing from this module keep working.
from memory_lab.query.evidence import (  # noqa: F401
    PROVENANCE_METADATA_KEYS,
    _clean_snippet,
    _provenance_metadata,
    _score_kind,
    normalize_evidence,
)


def _confidence_for(evidence: list[EvidenceItem]) -> tuple[float, str]:
    """Backward-compatible alias for the ask confidence helper."""
    from memory_lab.query.ask_projection import ask_confidence_for

    return ask_confidence_for(evidence)


def synthesize_answer(
    request: AskRequest,
    detection: IntentDetection,
    policy: ReasoningPolicy,
    evidence: list[EvidenceItem],
    workspace_id: str,
) -> AskResponse:
    """Deterministic/noop answer synthesis from evidence snippets only."""
    from memory_lab.query.ask_projection import (
        insufficient_evidence_response,
        successful_ask_response,
        unsupported_intent_response,
    )

    query = request.normalized_query()
    if detection.intent == "unknown" or not query:
        return unsupported_intent_response(intent=detection.intent, workspace_id=workspace_id)

    if len(evidence) < max(1, policy.min_evidence_items):
        return insufficient_evidence_response(
            intent=detection.intent,
            evidence=evidence,
            include_evidence=request.include_evidence,
            workspace_id=workspace_id,
        )

    return successful_ask_response(
        intent=detection.intent,
        evidence=evidence,
        include_evidence=request.include_evidence,
        workspace_id=workspace_id,
    )
