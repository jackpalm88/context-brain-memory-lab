from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from memory_lab.reasoning.models import EvidenceItem

from .models import (
    CONTEXT_PACK_NON_CLAIMS,
    CONTEXT_PACK_WARNINGS,
    PACK_VERSION,
    ContextPackBuildRequest,
    ContextPackBuildResponse,
    ContextPackEvidenceRef,
    ContextPackOmittedItem,
    ContextPackSummaryMetadata,
)

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def _none_last(value: Optional[str]) -> str:
    return value if value is not None else "~"


def _model_or_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return dict(value or {})


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


PROVENANCE_METADATA_KEYS = (
    "retrieval_mode",
    "retrieval_path",
    "embedding_status",
    "distance",
    "score_kind",
)


def _attach_provenance_metadata(row: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(meta)
    for key in PROVENANCE_METADATA_KEYS:
        value = row.get(key)
        if value is not None:
            enriched[key] = value
    return enriched


def evidence_from_item(item: EvidenceItem | Dict[str, Any], metadata: Optional[Dict[str, Any]] = None, *, role: Optional[str] = None) -> ContextPackEvidenceRef:
    row = _model_or_dict(item)
    meta = dict(row.get("metadata") or {})
    meta = _attach_provenance_metadata(row, meta)
    if metadata:
        meta.update({k: v for k, v in metadata.items() if v is not None})
    content_id = str(row.get("content_id") or "").strip()
    chunk_id = _clean_str(row.get("chunk_id"))
    evidence_id = _clean_str(row.get("evidence_id")) or f"ev_{content_id}_{chunk_id or 'content'}"
    return ContextPackEvidenceRef(
        evidence_id=evidence_id,
        content_id=content_id,
        chunk_id=chunk_id,
        rank=row.get("rank"),
        snippet=str(row.get("snippet") or row.get("text") or ""),
        score=float(row["score"]) if row.get("score") is not None else None,
        score_kind=row.get("score_kind"),
        memory_type=row.get("memory_type") or meta.get("memory_type"),
        memory_sub_type=row.get("memory_sub_type") or meta.get("memory_sub_type"),
        classify_confidence=row.get("classify_confidence") if row.get("classify_confidence") is not None else meta.get("classify_confidence"),
        is_current=row.get("is_current") if row.get("is_current") is not None else meta.get("is_current"),
        current_state_scope=row.get("current_state_scope") or meta.get("current_state_scope"),
        cs_supersedes_content_id=_clean_str(row.get("cs_supersedes_content_id") or meta.get("cs_supersedes_content_id")),
        role=role or row.get("role"),
        source=row.get("source") or row.get("retrieval_path"),
        metadata=meta or None,
    )


def _evidence_sort_key(e: ContextPackEvidenceRef):
    score = e.score if e.score is not None else -1.0
    rank = e.rank if e.rank is not None else 1_000_000
    return (rank, -score, e.content_id, _none_last(e.chunk_id))


def _current_sort_key(e: ContextPackEvidenceRef):
    rank = None
    if e.metadata:
        rank = e.metadata.get("canonical_rank")
    return (_none_last(e.current_state_scope), _none_last(e.memory_type), rank if rank is not None else 1_000_000, e.content_id)


def _stale_sort_key(e: ContextPackEvidenceRef):
    return (_none_last(e.current_state_scope), _none_last(e.memory_type), e.content_id)


def _conflict_sort_key(c: Dict[str, Any]):
    severity = SEVERITY_ORDER.get(str(c.get("severity") or "low"), 0)
    confidence = float(c.get("confidence") or 0.0)
    return (-severity, -confidence, str(c.get("conflict_type") or ""), str(c.get("conflict_id") or c.get("candidate_id") or ""))


def _dedupe_refs(refs: Iterable[ContextPackEvidenceRef]) -> List[ContextPackEvidenceRef]:
    seen = set()
    out: List[ContextPackEvidenceRef] = []
    for ref in refs:
        key = (ref.content_id, ref.chunk_id, ref.role, ref.evidence_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _counterfindings_from_conflicts(conflicts: List[Dict[str, Any]]) -> List[ContextPackEvidenceRef]:
    refs: List[ContextPackEvidenceRef] = []
    for conflict in conflicts:
        for ev in conflict.get("evidence") or []:
            evd = _model_or_dict(ev)
            role = evd.get("role")
            if role not in {"counterfinding", "contradicting"}:
                continue
            refs.append(evidence_from_item(evd, {"conflict_id": conflict.get("conflict_id") or conflict.get("candidate_id")}, role=role))
    return sorted(_dedupe_refs(refs), key=lambda e: (-(e.classify_confidence or 0.0), e.content_id, _none_last(e.chunk_id)))


def _stable_id_payload(
    *,
    workspace_id: str,
    request: ContextPackBuildRequest,
    supporting_evidence: List[ContextPackEvidenceRef],
    current_state_signals: List[ContextPackEvidenceRef],
    conflicts: List[Dict[str, Any]],
    stale_items: List[ContextPackEvidenceRef],
) -> Dict[str, Any]:
    return {
        "pack_version": PACK_VERSION,
        "workspace_id": workspace_id,
        "query": request.query,
        "scope": request.scope,
        "memory_types": request.resolved_memory_types() or [],
        "include_flags": {
            "include_conflicts": request.include_conflicts,
            "include_counterfindings": request.include_counterfindings,
            "include_current_state": request.include_current_state,
            "include_supporting_evidence": request.include_supporting_evidence,
        },
        "limit": request.limit,
        "supporting": sorted([{"content_id": e.content_id, "chunk_id": e.chunk_id} for e in supporting_evidence], key=lambda x: (x["content_id"], x.get("chunk_id") or "")),
        "current": sorted([e.content_id for e in current_state_signals]),
        "conflicts": sorted([str(c.get("conflict_id") or c.get("candidate_id") or "") for c in conflicts]),
        "stale": sorted([e.content_id for e in stale_items]),
    }


def make_context_pack_id(**kwargs: Any) -> str:
    payload = _stable_id_payload(**kwargs)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "cp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_context_pack(
    *,
    workspace_id: str,
    request: ContextPackBuildRequest,
    supporting_evidence: Optional[List[EvidenceItem | Dict[str, Any]]] = None,
    current_state_rows: Optional[List[Dict[str, Any]]] = None,
    conflict_candidates: Optional[List[Any]] = None,
    omitted_items: Optional[List[ContextPackOmittedItem | Dict[str, Any]]] = None,
) -> ContextPackBuildResponse:
    support_refs = [evidence_from_item(e, role="support") for e in (supporting_evidence or [])]
    support_refs = sorted(_dedupe_refs(support_refs), key=_evidence_sort_key)[: request.limit]

    current_refs: List[ContextPackEvidenceRef] = []
    stale_refs: List[ContextPackEvidenceRef] = []
    for row in current_state_rows or []:
        ref = evidence_from_item(row, row.get("metadata") if isinstance(row, dict) else None, role="current_state")
        if ref.is_current is True:
            current_refs.append(ref)
        elif ref.is_current is False or ref.cs_supersedes_content_id:
            stale_refs.append(ref)
    current_refs = sorted(_dedupe_refs(current_refs), key=_current_sort_key)[: request.limit]
    stale_refs = sorted(_dedupe_refs(stale_refs), key=_stale_sort_key)[: request.limit]

    conflicts = [_model_or_dict(c) for c in (conflict_candidates or [])]
    for c in conflicts:
        if not c.get("conflict_id") and c.get("candidate_id"):
            c["conflict_id"] = c["candidate_id"]
    conflicts = sorted(conflicts, key=_conflict_sort_key)[: request.limit]
    counterfindings = _counterfindings_from_conflicts(conflicts)[: request.limit] if request.include_counterfindings else []

    omissions: List[ContextPackOmittedItem] = []
    if omitted_items:
        for item in omitted_items:
            omissions.append(item if isinstance(item, ContextPackOmittedItem) else ContextPackOmittedItem(**item))
    omissions = sorted(omissions, key=lambda o: (o.reason, o.source))

    source_services: List[str] = []
    if request.include_supporting_evidence:
        source_services.append("retrieval")
    if request.include_current_state:
        source_services.append("current_state")
    if request.include_conflicts or request.include_counterfindings:
        source_services.append("conflicts")

    metadata = ContextPackSummaryMetadata(
        limits={"requested": request.limit, "applied": request.limit},
        include_flags={
            "include_supporting_evidence": request.include_supporting_evidence,
            "include_current_state": request.include_current_state,
            "include_conflicts": request.include_conflicts,
            "include_counterfindings": request.include_counterfindings,
        },
        memory_types=request.resolved_memory_types() or [],
        source_services=source_services,
    )
    context_pack_id = make_context_pack_id(
        workspace_id=workspace_id,
        request=request,
        supporting_evidence=support_refs,
        current_state_signals=current_refs,
        conflicts=conflicts,
        stale_items=stale_refs,
    )
    return ContextPackBuildResponse(
        context_pack_id=context_pack_id,
        workspace_id=workspace_id,
        query=request.query,
        scope=request.scope,
        summary_metadata=metadata,
        supporting_evidence=support_refs,
        current_state_signals=current_refs,
        conflict_candidates=conflicts,
        counterfindings=counterfindings,
        stale_or_superseded_items=stale_refs,
        omitted_items=omissions,
        warnings=list(CONTEXT_PACK_WARNINGS),
        non_claims=list(CONTEXT_PACK_NON_CLAIMS),
    )
