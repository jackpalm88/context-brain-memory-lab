"""DB-free deterministic conflict detector for B11.

B11 invariant: computed conflict candidates only. This module must not arbitrate
truth, mutate stored content, or call providers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from memory_lab.conflicts.markers import ParsedMarkers, extract_markers, is_support_only, normalize_scope
from memory_lab.conflicts.models import ConflictCandidate, ConflictEvidenceRef, make_candidate_id

_MIN_HIGH_CONF = 0.70
_SNIPPET_LIMIT = 220
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ConflictSourceRow:
    content_id: Optional[str]
    workspace_id: Optional[str]
    text: str = ""
    chunk_id: Optional[str] = None
    memory_type: Optional[str] = None
    memory_sub_type: Optional[str] = None
    classify_confidence: Optional[float] = None
    is_current: Optional[bool] = None
    current_state_scope: Optional[str] = None
    cs_supersedes_content_id: Optional[str] = None
    state_status: Optional[str] = None
    anchor_supersedes_content_id: Optional[str] = None


def _as_row(row: Any) -> ConflictSourceRow:
    return row if isinstance(row, ConflictSourceRow) else ConflictSourceRow(**row)


def _snippet(text: str) -> str:
    clean = _SPACE_RE.sub(" ", (text or "")).strip()
    return clean if len(clean) <= _SNIPPET_LIMIT else clean[: _SNIPPET_LIMIT - 1].rstrip() + "…"


def _row_scope(row: ConflictSourceRow, markers: ParsedMarkers) -> str:
    return normalize_scope(markers.scope or row.current_state_scope or "global")


def _eligible(row: ConflictSourceRow, workspace_id: str) -> bool:
    return bool(row.content_id and row.workspace_id == workspace_id)


def _high_conf(row: ConflictSourceRow) -> bool:
    return row.classify_confidence is None or row.classify_confidence >= _MIN_HIGH_CONF


def _evidence(row: ConflictSourceRow, role: str) -> ConflictEvidenceRef:
    cid = str(row.content_id)
    return ConflictEvidenceRef(
        evidence_id=f"ev_{cid}_{row.chunk_id or role}", content_id=cid, chunk_id=row.chunk_id,
        snippet=_snippet(row.text), memory_type=row.memory_type, memory_sub_type=row.memory_sub_type,
        classify_confidence=row.classify_confidence, is_current=row.is_current,
        current_state_scope=row.current_state_scope, role=role,  # type: ignore[arg-type]
    )


def _candidate(*, workspace_id: str, conflict_type: str, scope: str, status: str, severity: str,
               confidence: float, supporting: List[ConflictSourceRow], contradicting: List[ConflictSourceRow],
               evidence_roles: List[Tuple[ConflictSourceRow, str]], reason_codes: List[str],
               detection_rule: str, metadata: Optional[Dict[str, Any]] = None) -> ConflictCandidate:
    ids = [str(r.content_id) for r in supporting + contradicting if r.content_id]
    return ConflictCandidate(
        candidate_id=make_candidate_id(workspace_id=workspace_id, conflict_type=conflict_type, scope=scope, content_ids=ids, detection_rule=detection_rule),
        workspace_id=workspace_id, conflict_type=conflict_type, scope=scope, status=status, severity=severity, confidence=confidence,  # type: ignore[arg-type]
        supporting_content_ids=sorted({str(r.content_id) for r in supporting if r.content_id}),
        contradicting_content_ids=sorted({str(r.content_id) for r in contradicting if r.content_id}),
        evidence=[_evidence(r, role) for r, role in evidence_roles], reason_codes=reason_codes,
        detection_rule=detection_rule, metadata=metadata or {},
    )


def _dedupe(candidates: Iterable[ConflictCandidate]) -> List[ConflictCandidate]:
    out: Dict[str, ConflictCandidate] = {}
    for c in candidates:
        out.setdefault(c.candidate_id, c)
    return list(out.values())


def detect_conflict_candidates(rows: List[Any], *, workspace_id: str, scope: Optional[str] = None,
                               memory_type: Optional[str] = None, include_resolved: bool = True,
                               limit: int = 10) -> List[ConflictCandidate]:
    if not workspace_id:
        return []
    wanted_scope = normalize_scope(scope) if scope else None
    parsed: List[Tuple[ConflictSourceRow, ParsedMarkers, str]] = []
    for raw in rows:
        row = _as_row(raw)
        if not _eligible(row, workspace_id):
            continue
        if memory_type and row.memory_type != memory_type:
            continue
        markers = extract_markers(row.text or "")
        row_scope = _row_scope(row, markers)
        if wanted_scope and row_scope != wanted_scope:
            continue
        parsed.append((row, markers, row_scope))

    by_scope: Dict[str, List[Tuple[ConflictSourceRow, ParsedMarkers]]] = {}
    for row, markers, row_scope in parsed:
        by_scope.setdefault(row_scope, []).append((row, markers))

    candidates: List[ConflictCandidate] = []
    for row_scope, items in by_scope.items():
        support_rows = [r for r, m in items if m.support and is_support_only(m)]
        finding_rows = [r for r, m in items if not m.counterfinding and not m.contradiction and not is_support_only(m)]
        if not finding_rows:
            finding_rows = [r for r, m in items if not m.counterfinding and not m.contradiction]

        for row, markers in items:
            if markers.counterfinding:
                targets = [r for r in finding_rows if r.content_id != row.content_id and _high_conf(r)]
                if targets:
                    target = targets[0]
                    candidates.append(_candidate(
                        workspace_id=workspace_id, conflict_type="explicit_counterfinding", scope=row_scope,
                        status="unresolved", severity="medium" if _high_conf(row) else "low", confidence=0.85 if _high_conf(row) else 0.60,
                        supporting=[target] + support_rows, contradicting=[row],
                        evidence_roles=[(target, "finding"), (row, "counterfinding")] + [(s, "support") for s in support_rows if s.content_id != row.content_id],
                        reason_codes=["explicit_counterfinding_marker", "same_workspace", "same_scope_or_target"],
                        detection_rule="explicit_counterfinding_marker_v1",
                        metadata={"matched_markers": [mv.name for mv in markers.counterfinding], "memory_type": row.memory_type},
                    ))
            if markers.contradiction:
                targets = [r for r in finding_rows if r.content_id != row.content_id and _high_conf(r)]
                if targets:
                    target = targets[0]
                    candidates.append(_candidate(
                        workspace_id=workspace_id, conflict_type="explicit_contradiction", scope=row_scope,
                        status="unresolved", severity="high" if _high_conf(row) else "low", confidence=0.85 if _high_conf(row) else 0.60,
                        supporting=[target], contradicting=[row], evidence_roles=[(target, "finding"), (row, "contradicting")],
                        reason_codes=["explicit_contradiction_marker", "same_workspace", "same_scope_or_target"],
                        detection_rule="explicit_contradiction_marker_v1",
                        metadata={"matched_markers": [mv.name for mv in markers.contradiction], "memory_type": row.memory_type},
                    ))

        for current, _m in items:
            superseded = current.cs_supersedes_content_id or current.anchor_supersedes_content_id
            if not superseded or not _high_conf(current):
                continue
            stale_matches = [r for r, _ in items if r.content_id == str(superseded)]
            if stale_matches and include_resolved:
                stale = stale_matches[0]
                candidates.append(_candidate(
                    workspace_id=workspace_id, conflict_type="stale_current_tension", scope=row_scope,
                    status="resolved", severity="medium", confidence=0.90, supporting=[current], contradicting=[stale],
                    evidence_roles=[(current, "current"), (stale, "stale")],
                    reason_codes=["current_state_supersession", "same_workspace", "same_memory_type", "same_scope"],
                    detection_rule="current_state_supersession_v1", metadata={"memory_type": current.memory_type, "current_state_scope": row_scope},
                ))

        active_by_content_id: Dict[str, ConflictSourceRow] = {}
        for r, _ in items:
            if r.is_current is True and r.content_id:
                active_by_content_id.setdefault(str(r.content_id), r)
        active_rows = list(active_by_content_id.values())
        if len(active_rows) > 1:
            candidates.append(_candidate(
                workspace_id=workspace_id, conflict_type="stale_current_tension", scope=row_scope, status="unresolved", severity="high", confidence=0.80,
                supporting=[active_rows[0]], contradicting=[active_rows[1]], evidence_roles=[(active_rows[0], "current"), (active_rows[1], "current")],
                reason_codes=["multiple_current_anchors", "same_workspace", "same_scope"], detection_rule="multiple_current_anchors_v1",
                metadata={"memory_type": active_rows[0].memory_type, "current_state_scope": row_scope},
            ))

        claims: Dict[Tuple[str, str], Dict[str, ConflictSourceRow]] = {}
        for row, markers in items:
            if not _high_conf(row):
                continue
            for claim in markers.opposing_claims:
                claims.setdefault((claim.kind, claim.obj), {})[claim.polarity] = row
        for (kind, obj), polarities in claims.items():
            if "positive" in polarities and "negative" in polarities:
                pos, neg = polarities["positive"], polarities["negative"]
                candidates.append(_candidate(
                    workspace_id=workspace_id, conflict_type="same_scope_opposing_claim", scope=row_scope, status="unresolved",
                    severity="high" if pos.is_current and neg.is_current else "medium", confidence=0.80,
                    supporting=[pos], contradicting=[neg], evidence_roles=[(pos, "finding"), (neg, "contradicting")],
                    reason_codes=["same_scope_opposing_claim_markers", "exact_normalized_object_match"], detection_rule="same_scope_opposing_claim_v1",
                    metadata={"claim_kind": kind, "normalized_object": obj},
                ))

    ordered = sorted(_dedupe(candidates), key=lambda c: (c.severity != "high", -c.confidence, c.candidate_id))
    return ordered[: max(0, min(int(limit or 10), 50))]
