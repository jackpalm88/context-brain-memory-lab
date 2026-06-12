"""Models for B11 computed conflict candidates.

B11 invariant: computed conflict candidates only. This module must not arbitrate
truth, mutate stored content, or call providers.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ConflictType = Literal["explicit_counterfinding", "explicit_contradiction", "stale_current_tension", "same_scope_opposing_claim"]
ConflictStatus = Literal["unresolved", "resolved"]
ConflictSeverity = Literal["low", "medium", "high"]
EvidenceRole = Literal["finding", "counterfinding", "support", "contradicting", "stale", "current"]


class ConflictEvidenceRef(BaseModel):
    evidence_id: str
    content_id: str
    chunk_id: Optional[str] = None
    snippet: str
    memory_type: Optional[str] = None
    memory_sub_type: Optional[str] = None
    classify_confidence: Optional[float] = None
    is_current: Optional[bool] = None
    current_state_scope: Optional[str] = None
    role: EvidenceRole


class ConflictCandidate(BaseModel):
    candidate_id: str
    workspace_id: str
    conflict_type: ConflictType
    scope: str
    status: ConflictStatus
    severity: ConflictSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_content_ids: List[str] = Field(default_factory=list)
    contradicting_content_ids: List[str] = Field(default_factory=list)
    evidence: List[ConflictEvidenceRef] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    detection_rule: str
    metadata: Optional[Dict[str, Any]] = None
    conflict_id: Optional[str] = None


class ConflictSearchResponse(BaseModel):
    conflicts: List[ConflictCandidate] = Field(default_factory=list)
    count: int = 0
    mode: Literal["workspace_scoped_deterministic_conflict_candidates"] = "workspace_scoped_deterministic_conflict_candidates"
    workspace_id: str
    workspace_source: Optional[str] = None
    truth_arbitration: Literal[False] = False
    provider_backed_reasoning: Literal[False] = False


def make_candidate_id(*, workspace_id: str, conflict_type: str, scope: str, content_ids: List[str], detection_rule: str) -> str:
    normalized = "|".join([
        workspace_id or "",
        conflict_type or "",
        (scope or "global").strip().lower(),
        ",".join(sorted(str(c) for c in content_ids if c)),
        detection_rule or "",
    ])
    return "cc_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
