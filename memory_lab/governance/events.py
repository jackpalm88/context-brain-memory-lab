"""
Governance event contract for Memory Lab.

Append-only semantics are mandatory: emit_event() only INSERTs. Rollback and
override are represented as new events, never UPDATE/DELETE mutations.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

GOVERNANCE_EVENT_TYPE = "tier_transition_v1"
TRIGGER_TYPES = frozenset({"system", "human_override", "policy_engine"})
TRIGGER_SOURCES = frozenset({"save", "classify", "cleanup", "admin", "mcp"})


@dataclass
class TierTransitionEvent:
    event_id: str
    event_type: str
    content_id: str
    workspace_id: Optional[str]
    previous_tier: Optional[str]
    new_tier: str
    transition_reason: str
    transition_rule: str
    trigger_type: str
    trigger_source: str
    trace_id: str
    timestamp: str
    scores: Optional[Dict[str, float]] = None
    lineage_ref: Optional[str] = None


def validate_event(event: TierTransitionEvent) -> None:
    errors = []
    if event.event_type != GOVERNANCE_EVENT_TYPE:
        errors.append(f"event_type must be {GOVERNANCE_EVENT_TYPE!r}, got {event.event_type!r}")
    if not event.event_id:
        errors.append("event_id is required")
    if not event.content_id and event.new_tier != "discard":
        errors.append("content_id is required for non-discard events")
    if not event.new_tier:
        errors.append("new_tier is required")
    if not event.transition_reason:
        errors.append("transition_reason is required")
    if not event.transition_rule:
        errors.append("transition_rule is required")
    if event.trigger_type not in TRIGGER_TYPES:
        errors.append(f"trigger_type must be one of {sorted(TRIGGER_TYPES)}, got {event.trigger_type!r}")
    if event.trigger_source not in TRIGGER_SOURCES:
        errors.append(f"trigger_source must be one of {sorted(TRIGGER_SOURCES)}, got {event.trigger_source!r}")
    if not event.trace_id:
        errors.append("trace_id is required")
    if not event.timestamp:
        errors.append("timestamp is required")
    if errors:
        raise ValueError("[governance_events] Invalid tier_transition_v1: " + "; ".join(errors))


def build_event(
    content_id: str,
    workspace_id: Optional[str],
    previous_tier: Optional[str],
    new_tier: str,
    transition_reason: str,
    transition_rule: str,
    trigger_type: str,
    trigger_source: str,
    trace_id: str,
    scores: Optional[Dict[str, float]] = None,
    lineage_ref: Optional[str] = None,
) -> TierTransitionEvent:
    event = TierTransitionEvent(
        event_id=str(uuid.uuid4()),
        event_type=GOVERNANCE_EVENT_TYPE,
        content_id=content_id,
        workspace_id=workspace_id,
        previous_tier=previous_tier,
        new_tier=new_tier,
        transition_reason=transition_reason,
        transition_rule=transition_rule,
        trigger_type=trigger_type,
        trigger_source=trigger_source,
        trace_id=trace_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        scores=scores,
        lineage_ref=lineage_ref,
    )
    validate_event(event)
    return event


def emit_event(cur, event: TierTransitionEvent) -> None:
    """INSERT-only writer. Caller commits transaction after successful emit."""
    validate_event(event)
    cur.execute(
        """
        INSERT INTO cb_governance_events (
            event_id, event_type, content_id, workspace_id,
            previous_tier, new_tier,
            transition_reason, transition_rule,
            trigger_type, trigger_source,
            trace_id, scores, lineage_ref, created_at
        ) VALUES (
            %s::uuid, %s,
            CASE WHEN %s::text IS NOT NULL THEN %s::uuid ELSE NULL END,
            CASE WHEN %s::text IS NOT NULL THEN %s::uuid ELSE NULL END,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s::jsonb, %s, NOW()
        )
        """,
        (
            event.event_id,
            event.event_type,
            event.content_id,
            event.content_id,
            event.workspace_id,
            event.workspace_id,
            event.previous_tier,
            event.new_tier,
            event.transition_reason,
            event.transition_rule,
            event.trigger_type,
            event.trigger_source,
            event.trace_id,
            json.dumps(event.scores) if event.scores is not None else None,
            event.lineage_ref,
        ),
    )
    logger.info(
        "[governance_events] emitted event_id=%s type=%s content_id=%s trace_id=%s %s→%s",
        event.event_id,
        event.event_type,
        event.content_id,
        event.trace_id,
        event.previous_tier,
        event.new_tier,
    )
