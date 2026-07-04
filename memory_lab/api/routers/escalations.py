"""Gap-5: escalation queue — the human gate for conflicted content.

Constitution P-V: human approval defines epistemic trust boundaries. Approve
promotes the escalated content to ``persistent``; reject archives it (P-VIII:
forgetting is soft-delete, never hard-delete). Pending escalations past their
TTL resolve conservatively: reads synthesize ``expired`` and resolution is
refused (the TTL cleanup job owns the actual state flip).

All reads and writes are workspace-scoped through the auth context — unlike
production, an escalation in another workspace is a 404, not a shared queue.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.governance import events as gov

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/escalations", tags=["escalations"])

_RESOLVABLE_STATUSES = {"pending", "approved", "rejected", "expired"}


class EscalationSummary(BaseModel):
    escalation_id: str
    workspace_id: str
    content_id: Optional[str] = None
    conflict_content_id: Optional[str] = None
    conflict_type: str
    severity: str
    conflict_summary: Optional[str] = None
    status: str
    created_at: datetime
    expires_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


def _conn():
    return psycopg2.connect(get_settings().database_url)


def _effective_status(row: Dict[str, Any]) -> str:
    """Synthesize 'expired' for pending escalations past TTL without writing;
    the TTL cleanup job owns the actual state transition."""
    if row["status"] == "pending" and row.get("expired_now"):
        return "expired"
    return row["status"]


def _row_to_summary(row: Dict[str, Any]) -> EscalationSummary:
    return EscalationSummary(
        escalation_id=str(row["id"]),
        workspace_id=str(row["workspace_id"]),
        content_id=str(row["content_id"]) if row.get("content_id") else None,
        conflict_content_id=str(row["conflict_content_id"]) if row.get("conflict_content_id") else None,
        conflict_type=row["conflict_type"],
        severity=row["severity"],
        conflict_summary=row.get("conflict_summary"),
        status=_effective_status(row),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        resolved_at=row.get("resolved_at"),
        resolved_by=row.get("resolved_by"),
    )


_SELECT = """
    SELECT id, workspace_id, content_id, conflict_content_id,
           conflict_type, severity, conflict_summary, status,
           created_at, expires_at, resolved_at, resolved_by,
           (status = 'pending' AND expires_at < NOW()) AS expired_now
      FROM cb_escalations
"""


def _fetch_workspace_escalation(cur, escalation_id: str, workspace_id: str) -> Dict[str, Any]:
    try:
        _uuid.UUID(escalation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_escalation_id")
    cur.execute(
        _SELECT + " WHERE id = %s::uuid AND workspace_id = %s::uuid",
        (escalation_id, workspace_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="escalation not found")
    return dict(row)


@router.get("", response_model=List[EscalationSummary])
def list_escalations(
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|expired)$"),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_permission("escalations.read")),
) -> List[EscalationSummary]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = ["workspace_id = %s::uuid"]
            params: List[Any] = [auth.workspace_id]
            if status:
                conditions.append("status = %s")
                params.append(status)
            params.append(limit)
            cur.execute(
                _SELECT + f" WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT %s",
                tuple(params),
            )
            rows = cur.fetchall()
    return [_row_to_summary(dict(r)) for r in rows]


@router.get("/{escalation_id}", response_model=EscalationSummary)
def get_escalation(
    escalation_id: str,
    auth: AuthContext = Depends(require_permission("escalations.read")),
) -> EscalationSummary:
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            row = _fetch_workspace_escalation(cur, escalation_id, auth.workspace_id)
    return _row_to_summary(row)


def _resolve(escalation_id: str, auth: AuthContext, *, decision: str) -> EscalationSummary:
    """Shared approve/reject transition: pending → decision, content tier flip,
    governance event. Expired-pending refuses resolution (conservative gate)."""
    new_status = "approved" if decision == "approve" else "rejected"
    new_tier = "persistent" if decision == "approve" else "archived"
    tier_reason = f"escalation_{new_status}"
    trace_id = str(_uuid.uuid4())

    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            row = _fetch_workspace_escalation(cur, escalation_id, auth.workspace_id)
            if row["status"] != "pending":
                raise HTTPException(status_code=409, detail=f"escalation already {row['status']}")
            if row.get("expired_now"):
                raise HTTPException(status_code=409, detail="escalation expired")

            if row.get("content_id"):
                cur.execute(
                    "SELECT tier::text AS tier FROM content_items WHERE content_id = %s::uuid",
                    (row["content_id"],),
                )
                prev = cur.fetchone()
                previous_tier = prev["tier"] if prev else None
                cur.execute(
                    """
                    UPDATE content_items
                       SET tier = %s::memory_tier,
                           tier_reason = %s,
                           tier_assigned_at = NOW()
                     WHERE content_id = %s::uuid
                    """,
                    (new_tier, tier_reason, row["content_id"]),
                )
                event = gov.build_event(
                    content_id=str(row["content_id"]),
                    workspace_id=auth.workspace_id,
                    previous_tier=previous_tier,
                    new_tier=new_tier,
                    transition_reason=tier_reason,
                    transition_rule=f"ESCALATION_{new_status.upper()}_V1",
                    trigger_type="human_override",
                    trigger_source="admin",
                    trace_id=trace_id,
                )
                gov.emit_event(cur, event)

            cur.execute(
                """
                UPDATE cb_escalations
                   SET status = %s, resolved_at = NOW(), resolved_by = %s
                 WHERE id = %s::uuid
                RETURNING id, workspace_id, content_id, conflict_content_id,
                          conflict_type, severity, conflict_summary, status,
                          created_at, expires_at, resolved_at, resolved_by,
                          FALSE AS expired_now
                """,
                (new_status, auth.auth_subject_id, escalation_id),
            )
            updated = dict(cur.fetchone())
        conn.commit()
    logger.info(
        "[escalations] %s: id=%s content_id=%s by=%s trace_id=%s",
        new_status, escalation_id, row.get("content_id"), auth.auth_subject_id, trace_id,
    )
    return _row_to_summary(updated)


@router.post("/{escalation_id}/approve", response_model=EscalationSummary)
def approve_escalation(
    escalation_id: str,
    auth: AuthContext = Depends(require_permission("escalations.resolve")),
) -> EscalationSummary:
    """Approve — promotes escalated content to persistent tier (human gate)."""
    return _resolve(escalation_id, auth, decision="approve")


@router.post("/{escalation_id}/reject", response_model=EscalationSummary)
def reject_escalation(
    escalation_id: str,
    auth: AuthContext = Depends(require_permission("escalations.resolve")),
) -> EscalationSummary:
    """Reject — archives the escalated content (soft-delete, never hard-delete)."""
    return _resolve(escalation_id, auth, decision="reject")
