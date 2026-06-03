"""
P2C bounded cleanup admin route.

Caveat: this is an unauthenticated admin endpoint in the reviewed public
surface. Deployment/network controls must protect it. P2C keeps the route
bounded and dry-run safe; it does not redesign auth.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

import psycopg2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from memory_lab.api.config import get_settings
from memory_lab.governance import events as gov

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin-governance"])

RULE_TRANSIENT_TTL = "ttl_expired:transient_7d"


class CleanupRequest(BaseModel):
    dry_run: bool = True
    workspace_id: Optional[str] = None


class CleanupDetail(BaseModel):
    item_id: str
    item_type: str
    action: str


class CleanupResult(BaseModel):
    trace_id: str
    dry_run: bool
    escalations_expired: int
    content_archived: int
    skipped_conflicted: int
    skipped_pending_escalation: int
    details: List[CleanupDetail]


def _conn():
    return psycopg2.connect(get_settings().database_url)


@router.post("/admin/cleanup/ttl", response_model=CleanupResult)
def cleanup_ttl(body: CleanupRequest) -> CleanupResult:
    trace_id = str(uuid.uuid4())
    escalations_expired = 0
    content_archived = 0
    skipped_conflicted = 0
    skipped_pending_escalation = 0
    details: List[CleanupDetail] = []

    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text
                  FROM cb_escalations
                 WHERE status = 'pending'
                   AND expires_at < NOW()
                """
            )
            stale_esc_rows = cur.fetchall()
            escalations_expired = len(stale_esc_rows)

            if not body.dry_run:
                for row in stale_esc_rows:
                    cur.execute(
                        "UPDATE cb_escalations SET status = 'expired' WHERE id = %s::uuid",
                        (row["id"],),
                    )
                    logger.info("[cleanup/ttl] escalation expired: id=%s", row["id"])

            for row in stale_esc_rows:
                details.append(CleanupDetail(item_id=row["id"], item_type="escalation", action="expired"))

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                      FROM information_schema.columns
                     WHERE table_name = 'content_items'
                       AND column_name = 'workspace_id'
                ) AS has_workspace_id
                """
            )
            has_workspace_id = bool(cur.fetchone()["has_workspace_id"])

            if body.workspace_id and not has_workspace_id:
                raise HTTPException(
                    status_code=422,
                    detail="workspace_id filtering is unavailable in the public baseline: content_items.workspace_id is absent",
                )

            if has_workspace_id:
                ws_filter = ""
                params = []
                if body.workspace_id:
                    ws_filter = "AND workspace_id = %s::uuid"
                    params.append(body.workspace_id)

                cur.execute(
                    f"""
                    SELECT content_id::text, tier::text, workspace_id::text
                      FROM content_items
                     WHERE tier::text IN ('transient', 'conflicted')
                       AND created_at < NOW() - INTERVAL '7 days'
                       {ws_filter}
                    """,
                    tuple(params),
                )
            else:
                cur.execute(
                    """
                    SELECT content_id::text, tier::text, NULL::text AS workspace_id
                      FROM content_items
                     WHERE tier::text IN ('transient', 'conflicted')
                       AND created_at < NOW() - INTERVAL '7 days'
                    """
                )
            candidates = cur.fetchall()

            for row in candidates:
                cid = row["content_id"]
                tier = row["tier"]

                if tier == "conflicted":
                    skipped_conflicted += 1
                    continue

                cur.execute(
                    """
                    SELECT 1
                      FROM cb_escalations
                     WHERE content_id = %s::uuid AND status = 'pending'
                     LIMIT 1
                    """,
                    (cid,),
                )
                if cur.fetchone():
                    skipped_pending_escalation += 1
                    continue

                cur.execute(
                    "SELECT 1 FROM cb_hub_content WHERE content_id = %s LIMIT 1",
                    (cid,),
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    "SELECT 1 FROM cb_decision_nodes WHERE %s::uuid = ANY(source_content_ids) LIMIT 1",
                    (cid,),
                )
                if cur.fetchone():
                    continue

                content_archived += 1
                details.append(CleanupDetail(item_id=cid, item_type="content", action="archived"))

                if not body.dry_run:
                    cur.execute(
                        """
                        UPDATE content_items
                           SET tier = 'archived'::memory_tier,
                               tier_reason = %s
                         WHERE content_id = %s::uuid
                        """,
                        (RULE_TRANSIENT_TTL, cid),
                    )
                    event = gov.build_event(
                        content_id=cid,
                        workspace_id=row.get("workspace_id"),
                        previous_tier=tier,
                        new_tier="archived",
                        transition_reason=RULE_TRANSIENT_TTL,
                        transition_rule="TTL_TRANSIENT_7D",
                        trigger_type="system",
                        trigger_source="cleanup",
                        trace_id=trace_id,
                    )
                    gov.emit_event(cur, event)
                    logger.info(
                        "[cleanup/ttl] content archived: content_id=%s trace_id=%s event_id=%s",
                        cid, trace_id, event.event_id,
                    )
        if not body.dry_run:
            conn.commit()

    return CleanupResult(
        trace_id=trace_id,
        dry_run=body.dry_run,
        escalations_expired=escalations_expired,
        content_archived=content_archived,
        skipped_conflicted=skipped_conflicted,
        skipped_pending_escalation=skipped_pending_escalation,
        details=details,
    )
