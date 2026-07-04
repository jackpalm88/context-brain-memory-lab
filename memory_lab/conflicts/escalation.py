"""Gap-5: ingest-side conflict escalation (deterministic, provider-free).

Bridges the B11 computed conflict candidates into the Phase 7c human gate
(cb_escalations, migrations 014/015). Split into a pure planner
(plan_escalation_for_content) and a DB writer (persist_escalation) so the
decision logic is testable without a database.

Invariants:
- Deterministic: reuses the B11 detector; no providers, no truth arbitration.
- Max 1 escalation per save (highest severity wins).
- Only ``warning`` / ``requires_review`` escalate; ``informational`` stays silent.
- ``requires_review`` quarantines content to tier ``conflicted`` pending human
  action; ``warning`` only links the escalation. Human approval is the only
  path back to ``persistent`` (Constitution P-V).
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from memory_lab.conflicts.detector import detect_conflict_candidates
from memory_lab.conflicts.models import ConflictCandidate
from memory_lab.conflicts.service import _fetch_rows
from memory_lab.governance import events as gov

logger = logging.getLogger(__name__)

# B11 conflict_type -> cb_escalations.conflict_type (migration 014 CHECK constraint)
ESCALATION_CONFLICT_TYPE_MAP: Dict[str, str] = {
    "explicit_contradiction": "direct_contradiction",
    "same_scope_opposing_claim": "direct_contradiction",
    "explicit_counterfinding": "incompatible_assumption",
    "stale_current_tension": "outdated_assumption",
}

# B11 severity -> cb_escalations.severity; low never escalates.
SEVERITY_TO_ESCALATION: Dict[str, Optional[str]] = {
    "high": "requires_review",
    "medium": "warning",
    "low": None,
}

_DEFAULT_TTL_DAYS = {"requires_review": 30, "warning": 7}
_TTL_ENV = {
    "requires_review": "CB_ESCALATION_TTL_REQUIRES_REVIEW_DAYS",
    "warning": "CB_ESCALATION_TTL_WARNING_DAYS",
}


def _ttl_days(severity: str) -> int:
    raw = os.environ.get(_TTL_ENV[severity], "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_TTL_DAYS[severity]


@dataclass(frozen=True)
class EscalationPlan:
    workspace_id: str
    content_id: str
    conflict_content_id: Optional[str]
    conflict_type: str
    severity: str
    conflict_summary: str
    ttl_days: int
    candidate_id: str
    detection_rule: str


def _counterpart_id(candidate: ConflictCandidate, content_id: str) -> Optional[str]:
    for ids in (candidate.contradicting_content_ids, candidate.supporting_content_ids):
        for cid in ids:
            if cid != content_id:
                return cid
    return None


def plan_escalation_for_content(
    candidates: List[ConflictCandidate], *, workspace_id: str, content_id: str
) -> Optional[EscalationPlan]:
    """Pick at most one escalation for a freshly saved content_id.

    Candidates arrive severity-sorted from the detector; the first unresolved
    candidate that involves content_id wins.
    """
    for candidate in candidates:
        if candidate.status != "unresolved":
            continue
        involved = set(candidate.supporting_content_ids) | set(candidate.contradicting_content_ids)
        if content_id not in involved:
            continue
        severity = SEVERITY_TO_ESCALATION.get(candidate.severity)
        if severity is None:
            continue
        conflict_type = ESCALATION_CONFLICT_TYPE_MAP.get(candidate.conflict_type)
        if conflict_type is None:
            continue
        counterpart = _counterpart_id(candidate, content_id)
        summary = (
            f"candidate_id={candidate.candidate_id} rule={candidate.detection_rule} "
            f"b11_type={candidate.conflict_type} b11_severity={candidate.severity} "
            f"confidence={candidate.confidence:.2f} "
            f"reasons={','.join(candidate.reason_codes)} "
            f"counterpart_content_id={counterpart or 'unknown'}"
        )[:500]
        return EscalationPlan(
            workspace_id=workspace_id,
            content_id=content_id,
            conflict_content_id=counterpart,
            conflict_type=conflict_type,
            severity=severity,
            conflict_summary=summary,
            ttl_days=_ttl_days(severity),
            candidate_id=candidate.candidate_id,
            detection_rule=candidate.detection_rule,
        )
    return None


def persist_escalation(conn: Any, plan: EscalationPlan) -> Dict[str, Any]:
    """INSERT the escalation row and quarantine content when requires_review.

    Caller owns the connection; this commits on success.
    """
    trace_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cb_escalations (
                workspace_id, content_id, conflict_content_id,
                conflict_type, severity, conflict_summary, status, expires_at
            ) VALUES (
                %s::uuid, %s::uuid, %s::uuid,
                %s, %s, %s, 'pending', NOW() + make_interval(days => %s)
            )
            RETURNING id::text
            """,
            (
                plan.workspace_id,
                plan.content_id,
                plan.conflict_content_id,
                plan.conflict_type,
                plan.severity,
                plan.conflict_summary,
                plan.ttl_days,
            ),
        )
        escalation_id = cur.fetchone()[0]

        if plan.severity == "requires_review":
            cur.execute(
                "SELECT tier::text FROM content_items WHERE content_id = %s::uuid",
                (plan.content_id,),
            )
            prev = cur.fetchone()
            previous_tier = prev[0] if prev else None
            cur.execute(
                """
                UPDATE content_items
                   SET tier = 'conflicted'::memory_tier,
                       tier_reason = 'conflict:requires_review',
                       tier_assigned_at = NOW(),
                       conflict_escalation_id = %s::uuid
                 WHERE content_id = %s::uuid
                """,
                (escalation_id, plan.content_id),
            )
            event = gov.build_event(
                content_id=plan.content_id,
                workspace_id=plan.workspace_id,
                previous_tier=previous_tier,
                new_tier="conflicted",
                transition_reason="conflict:requires_review",
                transition_rule="CONFLICT_REQUIRES_REVIEW_V1",
                trigger_type="system",
                trigger_source="save",
                trace_id=trace_id,
            )
            gov.emit_event(cur, event)
        else:
            cur.execute(
                "UPDATE content_items SET conflict_escalation_id = %s::uuid WHERE content_id = %s::uuid",
                (escalation_id, plan.content_id),
            )
    conn.commit()
    logger.info(
        "[conflict_escalation] escalation created: id=%s severity=%s type=%s content_id=%s trace_id=%s",
        escalation_id, plan.severity, plan.conflict_type, plan.content_id, trace_id,
    )
    return {
        "conflict_escalation_id": escalation_id,
        "conflict_type": plan.conflict_type,
        "conflict_severity": plan.severity,
        "conflict_content_id": plan.conflict_content_id,
        "conflict_status": "pending",
        "conflict_detection_rule": plan.detection_rule,
    }


def evaluate_and_escalate_on_ingest(
    conn: Any, *, workspace_id: Optional[str], content_id: str, source_limit: int = 100
) -> Optional[Dict[str, Any]]:
    """Detect conflicts for a just-saved content row; escalate the top one.

    Returns escalation meta for the save response, or None when nothing
    actionable. Deterministic and provider-free; caller wraps for best-effort.
    """
    if not workspace_id or not content_id:
        return None
    rows = _fetch_rows(
        conn,
        workspace_id=workspace_id,
        query=None,
        scope=None,
        memory_type=None,
        memory_types=None,
        source_limit=source_limit,
    )
    candidates = detect_conflict_candidates(
        rows, workspace_id=workspace_id, include_resolved=False, limit=10
    )
    plan = plan_escalation_for_content(candidates, workspace_id=workspace_id, content_id=content_id)
    if plan is None:
        return None
    return persist_escalation(conn, plan)
