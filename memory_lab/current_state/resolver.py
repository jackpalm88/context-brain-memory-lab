"""Deterministic current-state resolver.

B10 scope:
- provider-free and SQL-backed
- handles exactly one already-persisted content item
- callable by synchronous ingest today and future reconcile/catchup jobs
- owns only current-state fields and cb_current_state_anchors

Classify owns memory_type/memory_sub_type/classify_confidence/history; this module owns
content_items.is_current, content_items.current_state_scope,
content_items.cs_supersedes_content_id, and cb_current_state_anchors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from memory_lab.current_state.scope_pipeline import _extract_marker, _slugify_scope, resolve_scope


_MIN_CONFIDENCE = 0.70
_ALLOWED_SET_BY = {"auto_classify", "human_override", "mcp_tool", "api", "reconcile_job"}


@dataclass(frozen=True)
class CurrentStateResolution:
    """Structured result returned by the current-state resolver."""

    status: str
    reason: str
    content_id: Optional[str] = None
    workspace_id: Optional[str] = None
    memory_type: Optional[str] = None
    current_state_scope: Optional[str] = None
    scope_source: Optional[str] = None
    state_identity: Optional[str] = None
    anchor_id: Optional[str] = None
    supersedes_content_id: Optional[str] = None
    wrote: bool = False
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "content_id": self.content_id,
            "workspace_id": self.workspace_id,
            "memory_type": self.memory_type,
            "current_state_scope": self.current_state_scope,
            "scope_source": self.scope_source,
            "state_identity": self.state_identity,
            "anchor_id": self.anchor_id,
            "supersedes_content_id": self.supersedes_content_id,
            "wrote": self.wrote,
            "idempotent": self.idempotent,
        }


def _first_nonempty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return None


def derive_current_state_scope(
    *,
    content_text: Optional[str] = None,
    project_topic: Optional[str] = None,
    domain_hint: Optional[str] = None,
) -> str:
    """Derive a stable current-state scope using the B10 v1 deterministic order.

    Kept as the DB-free subset of the FV-FIX-2B pipeline (marker → project_topic
    → domain_hint → global) for callers without a connection.
    """

    marker = _extract_marker(content_text)
    return _slugify_scope(_first_nonempty(marker, project_topic, domain_hint, "global"))


def resolve_current_state_after_ingest(
    conn: Any,
    *,
    workspace_id: Optional[str],
    content_id: Optional[str],
    memory_type: Optional[str],
    memory_sub_type: Optional[str] = None,
    classify_confidence: Optional[float],
    signals: Optional[Sequence[str]] = None,
    scope_hint: Optional[str] = None,
    project_topic: Optional[str] = None,
    domain_hint: Optional[str] = None,
    content_text: Optional[str] = None,
    set_by: str = "auto_classify",
    state_identity: Optional[str] = None,
) -> CurrentStateResolution:
    """Resolve one persisted content item into the current-state anchor chain.

    Low-confidence, missing-workspace, or missing-content inputs are explicit no-ops.
    The function is idempotent for the same active content_id.

    Phase A (decision 4a11008b): current_state_scope is grouping only and NEVER
    triggers supersession by itself. state_identity is the only thing that can mark
    a prior anchor superseded, and it must already be authorized by the caller before
    this function is invoked (see ApiAdapter.create_content_minimal's
    state_identity_trusted gate) — this function trusts whatever state_identity it is
    given, the same way it already trusts set_by. Without state_identity, this call
    only updates content_items.current_state_scope for retrieval grouping and never
    touches cb_current_state_anchors.
    """

    if classify_confidence is None or classify_confidence < _MIN_CONFIDENCE:
        return CurrentStateResolution(
            status="noop", reason="low_confidence", content_id=content_id,
            workspace_id=workspace_id, memory_type=memory_type, wrote=False,
        )
    if not workspace_id:
        return CurrentStateResolution(
            status="noop", reason="missing_workspace", content_id=content_id,
            memory_type=memory_type, wrote=False,
        )
    if not content_id:
        return CurrentStateResolution(
            status="noop", reason="missing_content_id", workspace_id=workspace_id,
            memory_type=memory_type, wrote=False,
        )
    if not memory_type:
        return CurrentStateResolution(
            status="noop", reason="missing_memory_type", content_id=content_id,
            workspace_id=workspace_id, wrote=False,
        )
    if set_by not in _ALLOWED_SET_BY:
        return CurrentStateResolution(
            status="noop", reason="invalid_set_by", content_id=content_id,
            workspace_id=workspace_id, memory_type=memory_type, wrote=False,
        )

    scope_resolution = resolve_scope(
        conn,
        workspace_id=workspace_id,
        content_text=content_text,
        scope_hint=scope_hint,
        project_topic=project_topic,
        domain_hint=domain_hint,
    )
    scope = scope_resolution.scope
    scope_source = scope_resolution.source

    if not state_identity:
        # Phase A group-only path: current_state_scope keeps working for retrieval,
        # but nothing about a bare scope match may ever supersede anything. This is
        # the entire fix for the false-supersession bug — no new machinery, just the
        # absence of the old trigger condition.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE content_items SET current_state_scope = %s WHERE content_id = %s::uuid",
                (scope, content_id),
            )
            conn.commit()
        return CurrentStateResolution(
            status="grouped", reason="scope_only_no_state_identity",
            content_id=content_id, workspace_id=workspace_id, memory_type=memory_type,
            current_state_scope=scope, scope_source=scope_source, wrote=True, idempotent=False,
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT anchor_id::text, supersedes_content_id::text
              FROM cb_current_state_anchors
             WHERE workspace_id = %s::uuid
               AND memory_type = %s
               AND state_identity = %s
               AND content_id = %s::uuid
               AND state_status = 'active'
             LIMIT 1
            """,
            (workspace_id, memory_type, state_identity, content_id),
        )
        existing_same = cur.fetchone()
        if existing_same:
            anchor_id, supersedes_id = existing_same[0], existing_same[1]
            cur.execute(
                """
                UPDATE content_items
                   SET is_current = TRUE,
                       current_state_scope = %s,
                       state_identity = %s,
                       cs_supersedes_content_id = %s::uuid
                 WHERE content_id = %s::uuid
                """,
                (scope, state_identity, supersedes_id, content_id),
            )
            conn.commit()
            return CurrentStateResolution(
                status="active", reason="idempotent_active_anchor",
                content_id=content_id, workspace_id=workspace_id, memory_type=memory_type,
                current_state_scope=scope, scope_source=scope_source, state_identity=state_identity,
                anchor_id=anchor_id, supersedes_content_id=supersedes_id, wrote=True, idempotent=True,
            )

        cur.execute(
            """
            SELECT content_id::text
              FROM cb_current_state_anchors
             WHERE workspace_id = %s::uuid
               AND memory_type = %s
               AND state_identity = %s
               AND state_status = 'active'
               AND content_id IS NOT NULL
             ORDER BY canonical_rank ASC, valid_from DESC
             LIMIT 1
            """,
            (workspace_id, memory_type, state_identity),
        )
        previous = cur.fetchone()
        supersedes_id = previous[0] if previous else None

        cur.execute(
            """
            UPDATE cb_current_state_anchors
               SET state_status = 'superseded',
                   valid_until = NOW(),
                   updated_at = NOW()
             WHERE workspace_id = %s::uuid
               AND memory_type = %s
               AND state_identity = %s
               AND state_status = 'active'
               AND (content_id IS NULL OR content_id <> %s::uuid)
            """,
            (workspace_id, memory_type, state_identity, content_id),
        )
        if supersedes_id:
            cur.execute(
                """
                UPDATE content_items
                   SET is_current = FALSE,
                       current_state_scope = %s
                 WHERE content_id = %s::uuid
                """,
                (scope, supersedes_id),
            )

        cur.execute(
            """
            INSERT INTO cb_current_state_anchors
                (workspace_id, memory_type, scope, state_identity, content_id, supersedes_content_id,
                 state_status, state_reason, set_by)
            VALUES
                (%s::uuid, %s, %s, %s, %s::uuid, %s::uuid,
                 'active', %s, %s)
            RETURNING anchor_id::text
            """,
            (
                workspace_id,
                memory_type,
                scope,
                state_identity,
                content_id,
                supersedes_id,
                f"classify_confidence={classify_confidence:.4f}; memory_sub_type={memory_sub_type or ''}; signals={list(signals or [])}; scope_source={scope_source}; state_identity={state_identity}",
                set_by,
            ),
        )
        anchor_id = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE content_items
               SET is_current = TRUE,
                   current_state_scope = %s,
                   state_identity = %s,
                   cs_supersedes_content_id = %s::uuid
             WHERE content_id = %s::uuid
            """,
            (scope, state_identity, supersedes_id, content_id),
        )
        conn.commit()

    return CurrentStateResolution(
        status="active", reason="resolved_current_state",
        content_id=content_id, workspace_id=workspace_id, memory_type=memory_type,
        current_state_scope=scope, scope_source=scope_source, state_identity=state_identity,
        anchor_id=anchor_id, supersedes_content_id=supersedes_id, wrote=True, idempotent=False,
    )
