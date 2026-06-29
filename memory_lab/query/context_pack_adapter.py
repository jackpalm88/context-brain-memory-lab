from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest, ContextPackBuildResponse, ContextPackEvidenceRef
from memory_lab.reasoning.models import AskRequest, EvidenceItem

_ORIGINAL_ASK_EVIDENCE_KEY = "_query_service_original_evidence_item"


def _item_for_context_pack(item: EvidenceItem) -> dict:
    """Return a context-pack input row that carries exact ask evidence for lossless projection.

    ContextPackEvidenceRef intentionally has a smaller public shape than EvidenceItem.
    QueryService still needs exact AskResponse parity, so the support-only internal seam
    stores the original EvidenceItem dump in private metadata and removes it again when
    projecting support refs back to EvidenceItem.
    """
    row = item.model_dump()
    original = deepcopy(row)
    metadata = dict(row.get("metadata") or {})
    metadata[_ORIGINAL_ASK_EVIDENCE_KEY] = original
    row["metadata"] = metadata
    return row


def build_support_only_context_pack_for_ask(
    *,
    request: AskRequest,
    workspace_id: str,
    query: str,
    evidence: Iterable[EvidenceItem],
    limit: int,
) -> ContextPackBuildResponse:
    """Build QueryService internal support-only context pack without extra retrieval.

    This uses the low-level context-pack builder and deliberately disables current-state,
    conflicts, and counterfindings so /v1/ask behavior remains evidence-parity-only.
    """
    pack_request = ContextPackBuildRequest(
        query=query or None,
        scope=query or "ask",
        include_supporting_evidence=True,
        include_current_state=False,
        include_conflicts=False,
        include_counterfindings=False,
        limit=limit,
    )
    return build_context_pack(
        workspace_id=workspace_id,
        request=pack_request,
        supporting_evidence=[_item_for_context_pack(item) for item in evidence],
        current_state_rows=[],
        conflict_candidates=[],
    )


def support_ref_to_evidence_item(ref: ContextPackEvidenceRef) -> EvidenceItem:
    metadata = dict(ref.metadata or {})
    original = metadata.pop(_ORIGINAL_ASK_EVIDENCE_KEY, None)
    if isinstance(original, dict):
        return EvidenceItem(**original)

    retrieval_path = str(metadata.get("retrieval_path") or ref.source or "deterministic_db").strip() or "deterministic_db"
    source = metadata.get("source") or ref.source
    title = metadata.get("title")
    return EvidenceItem(
        evidence_id=ref.evidence_id,
        rank=ref.rank or 0,
        content_id=ref.content_id,
        chunk_id=ref.chunk_id,
        snippet=ref.snippet,
        score=ref.score,
        score_kind=ref.score_kind or str(metadata.get("score_kind") or "chunk_text_match"),
        retrieval_path=retrieval_path,
        source=source,
        title=title,
        metadata=metadata or None,
    )


def evidence_items_from_supporting_context_pack(context_pack: ContextPackBuildResponse) -> list[EvidenceItem]:
    """Project support refs back to EvidenceItem for existing ask synthesis."""
    return [support_ref_to_evidence_item(ref) for ref in context_pack.supporting_evidence]
