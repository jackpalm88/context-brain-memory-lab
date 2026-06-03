"""
P2C admin tier override / rollback surface.

Caveat: these are unauthenticated admin endpoints in the reviewed public
surface. They must be protected by deployment/network controls; P2C does not
redesign auth.
"""
from __future__ import annotations

import logging
import uuid as _uuid_lib
from datetime import datetime, timezone
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from memory_lab.api.config import get_settings
from memory_lab.governance import events as _gov
from memory_lab.governance.transition_matrix import GovernanceTransitionError, validate_transition

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin-governance"])

_TERMINAL_STATES = frozenset({"archived", "decayed", "superseded"})
_OVERRIDE_TIER_MAP = {
    "force_persist": "persistent",
    "force_discard": "archived",
}


class TierOverrideRequest(BaseModel):
    override_action: str = Field(..., description="'force_persist' or 'force_discard'")
    override_by: str = Field(..., min_length=1, description="Actor performing the override")
    override_reason: str = Field(..., min_length=1, description="Human-readable justification")
    workspace_id: Optional[str] = None


class TierOverrideResponse(BaseModel):
    content_id: str
    override_action: str
    override_by: str
    override_reason: str
    previous_tier: Optional[str]
    new_tier: str
    trace_id: str
    timestamp: str
    governance_event_id: str


class TierRollbackRequest(BaseModel):
    rollback_by: str = Field(..., min_length=1, description="Actor performing the rollback")
    rollback_reason: str = Field(..., min_length=1, description="Justification for the rollback")
    workspace_id: Optional[str] = None


class TierRollbackResponse(BaseModel):
    content_id: str
    rolled_back_from: str
    rolled_back_to: Optional[str]
    rollback_by: str
    rollback_reason: str
    trace_id: str
    timestamp: str
    governance_event_id: str
    prior_event_id: Optional[str]


def _conn():
    return psycopg2.connect(get_settings().database_url)


def _fetch_content_tier(cur, content_id: str) -> Optional[str]:
    cur.execute(
        "SELECT tier::text FROM content_items WHERE content_id = %s::uuid",
        (content_id,),
    )
    row = cur.fetchone()
    return row["tier"] if row else None


def _update_content_tier(cur, content_id: str, new_tier: str, tier_reason: str) -> None:
    cur.execute(
        """
        UPDATE content_items
           SET tier = %s::memory_tier,
               tier_assigned_at = NOW(),
               tier_reason = %s
         WHERE content_id = %s::uuid
        """,
        (new_tier, tier_reason, content_id),
    )


@router.post("/admin/content/{content_id}/tier/override", response_model=TierOverrideResponse)
def tier_override(content_id: str, payload: TierOverrideRequest):
    if payload.override_action not in _OVERRIDE_TIER_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown override_action {payload.override_action!r}. Must be one of: {sorted(_OVERRIDE_TIER_MAP.keys())}",
        )

    new_tier = _OVERRIDE_TIER_MAP[payload.override_action]
    trace_id = _uuid_lib.uuid4().hex[:16]
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                previous_tier = _fetch_content_tier(cur, content_id)
                if previous_tier is None:
                    raise HTTPException(status_code=404, detail=f"Content {content_id} not found")

                try:
                    validate_transition(previous_tier=previous_tier, new_tier=new_tier, trigger_type="human_override")
                except GovernanceTransitionError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc

                _update_content_tier(cur, content_id, new_tier, "governance_override:human")
                event = _gov.build_event(
                    content_id=content_id,
                    workspace_id=payload.workspace_id,
                    previous_tier=previous_tier,
                    new_tier=new_tier,
                    transition_reason=(
                        f"human_override:{payload.override_action}:"
                        f"by={payload.override_by}:"
                        f"reason={payload.override_reason[:200]}"
                    ),
                    transition_rule=f"OVERRIDE-{payload.override_action.upper()}",
                    trigger_type="human_override",
                    trigger_source="admin",
                    trace_id=trace_id,
                )
                _gov.emit_event(cur, event)
            conn.commit()
    except HTTPException:
        raise

    logger.info(
        "[tier_override] content_id=%s %s→%s by=%s trace_id=%s",
        content_id, previous_tier, new_tier, payload.override_by, trace_id,
    )
    return TierOverrideResponse(
        content_id=content_id,
        override_action=payload.override_action,
        override_by=payload.override_by,
        override_reason=payload.override_reason,
        previous_tier=previous_tier,
        new_tier=new_tier,
        trace_id=trace_id,
        timestamp=timestamp,
        governance_event_id=event.event_id,
    )


@router.post("/admin/content/{content_id}/tier/rollback", response_model=TierRollbackResponse)
def tier_rollback(content_id: str, payload: TierRollbackRequest):
    trace_id = _uuid_lib.uuid4().hex[:16]
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                current_tier = _fetch_content_tier(cur, content_id)
                if current_tier is None:
                    raise HTTPException(status_code=404, detail=f"Content {content_id} not found")

                cur.execute(
                    """
                    SELECT event_id::text, previous_tier, new_tier, trigger_source, created_at
                      FROM cb_governance_events
                     WHERE content_id = %s::uuid
                     ORDER BY created_at DESC
                     LIMIT 2
                    """,
                    (content_id,),
                )
                events = cur.fetchall()
                if not events:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"No governance event history found for content {content_id}. "
                            "Cannot determine prior state — rollback unavailable."
                        ),
                    )

                latest_event = events[0]
                prior_tier = latest_event["previous_tier"]
                is_cleanup_archive_rollback = (
                    current_tier == "archived"
                    and latest_event["new_tier"] == "archived"
                    and latest_event["trigger_source"] == "cleanup"
                    and prior_tier is not None
                )

                if current_tier in _TERMINAL_STATES and not is_cleanup_archive_rollback:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Cannot roll back from terminal tier {current_tier!r}. "
                            "Terminal states are irreversible by design unless the latest "
                            "archived transition was emitted by cleanup with previous_tier."
                        ),
                    )

                if prior_tier is None:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Most recent event was the initial tier assignment (previous_tier=None). "
                            "There is no prior tier to restore. Use force_discard override to archive if needed."
                        ),
                    )

                if not is_cleanup_archive_rollback:
                    try:
                        validate_transition(previous_tier=current_tier, new_tier=prior_tier, trigger_type="human_override")
                    except GovernanceTransitionError as exc:
                        raise HTTPException(status_code=422, detail=str(exc)) from exc

                _update_content_tier(cur, content_id, prior_tier, "governance_override:rollback")
                rollback_event = _gov.build_event(
                    content_id=content_id,
                    workspace_id=payload.workspace_id,
                    previous_tier=current_tier,
                    new_tier=prior_tier,
                    transition_reason=(
                        f"rollback:by={payload.rollback_by}:"
                        f"reason={payload.rollback_reason[:200]}:"
                        f"reverts_event={latest_event['event_id']}"
                    ),
                    transition_rule="ROLLBACK",
                    trigger_type="human_override",
                    trigger_source="admin",
                    trace_id=trace_id,
                )
                _gov.emit_event(cur, rollback_event)
            conn.commit()
    except HTTPException:
        raise

    logger.info(
        "[tier_rollback] content_id=%s %s→%s by=%s trace_id=%s reverts=%s",
        content_id, current_tier, prior_tier, payload.rollback_by, trace_id, latest_event["event_id"],
    )
    return TierRollbackResponse(
        content_id=content_id,
        rolled_back_from=current_tier,
        rolled_back_to=prior_tier,
        rollback_by=payload.rollback_by,
        rollback_reason=payload.rollback_reason,
        trace_id=trace_id,
        timestamp=timestamp,
        governance_event_id=rollback_event.event_id,
        prior_event_id=latest_event["event_id"],
    )
