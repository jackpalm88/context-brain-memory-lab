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

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence


_MIN_CONFIDENCE = 0.70
_MAX_SCOPE_LEN = 120
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


def _slugify_scope(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "global"
    raw = re.sub(r"[`'\"<>]", "", raw)
    raw = re.sub(r"[^a-z0-9._:/-]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-._:/")
    return (raw[:_MAX_SCOPE_LEN].strip("-._:/") or "global")


def derive_current_state_scope(
    *,
    content_text: Optional[str] = None,
    project_topic: Optional[str] = None,
    domain_hint: Optional[str] = None,
) -> str:
    """Derive a stable current-state scope using the B10 v1 deterministic order."""

    text = content_text or ""
    marker = None
    for pattern in (
        r"(?im)^\s*current_state_scope\s*[:=]\s*([^\n#;]+)",
        r"(?im)^\s*current-state-scope\s*[:=]\s*([^\n#;]+)",
        r"(?im)^\s*scope\s*[:=]\s*([^\n#;]+)",
        r"(?im)^\s*anchor\s*[:=]\s*([^\n#;]+)",
    ):
        match = re.search(pattern, text)
        if match:
            marker = match.group(1)
            break

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
    project_topic: Optional[str] = None,
    domain_hint: Optional[str] = None,
    content_text: Optional[str] = None,
    set_by: str = "auto_classify",
) -> CurrentStateResolution:
    """Resolve one persisted content item into the current-state anchor chain.

    Low-confidence, missing-workspace, or missing-content inputs are explicit no-ops.
    The function is idempotent for the same active content_id.
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

    scope = derive_current_state_scope(
        content_text=content_text, project_topic=project_topic, domain_hint=domain_hint
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT anchor_id::text, supersedes_content_id::text
              FROM cb_current_state_anchors
             WHERE workspace_id = %s::uuid
               AND memory_type = %s
               AND scope = %s
               AND content_id = %s::uuid
               AND state_status = 'active'
             LIMIT 1
            """,
            (workspace_id, memory_type, scope, content_id),
        )
        existing_same = cur.fetchone()
        if existing_same:
            anchor_id, supersedes_id = existing_same[0], existing_same[1]
            cur.execute(
                """
                UPDATE content_items
                   SET is_current = TRUE,
                       current_state_scope = %s,
                       cs_supersedes_content_id = %s::uuid
                 WHERE content_id = %s::uuid
                """,
                (scope, supersedes_id, content_id),
            )
            conn.commit()
            return CurrentStateResolution(
                status="active", reason="idempotent_active_anchor",
                content_id=content_id, workspace_id=workspace_id, memory_type=memory_type,
                current_state_scope=scope, anchor_id=anchor_id,
                supersedes_content_id=supersedes_id, wrote=True, idempotent=True,
            )

        cur.execute(
            """
            SELECT content_id::text
              FROM cb_current_state_anchors
             WHERE workspace_id = %s::uuid
               AND memory_type = %s
               AND scope = %s
               AND state_status = 'active'
               AND content_id IS NOT NULL
             ORDER BY canonical_rank ASC, valid_from DESC
             LIMIT 1
            """,
            (workspace_id, memory_type, scope),
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
               AND scope = %s
               AND state_status = 'active'
               AND (content_id IS NULL OR content_id <> %s::uuid)
            """,
            (workspace_id, memory_type, scope, content_id),
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
                (workspace_id, memory_type, scope, content_id, supersedes_content_id,
                 state_status, state_reason, set_by)
            VALUES
                (%s::uuid, %s, %s, %s::uuid, %s::uuid,
                 'active', %s, %s)
            RETURNING anchor_id::text
            """,
            (
                workspace_id,
                memory_type,
                scope,
                content_id,
                supersedes_id,
                f"classify_confidence={classify_confidence:.4f}; memory_sub_type={memory_sub_type or ''}; signals={list(signals or [])}",
                set_by,
            ),
        )
        anchor_id = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE content_items
               SET is_current = TRUE,
                   current_state_scope = %s,
                   cs_supersedes_content_id = %s::uuid
             WHERE content_id = %s::uuid
            """,
            (scope, supersedes_id, content_id),
        )
        conn.commit()

    return CurrentStateResolution(
        status="active", reason="resolved_current_state",
        content_id=content_id, workspace_id=workspace_id, memory_type=memory_type,
        current_state_scope=scope, anchor_id=anchor_id,
        supersedes_content_id=supersedes_id, wrote=True, idempotent=False,
    )
