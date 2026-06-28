from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID
import json

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from .models import (
    ConflictPair,
    DecisionConflictsResponse,
    DecisionCreate,
    DecisionFull,
    DecisionLineageResponse,
    DecisionListResponse,
    DecisionSummary,
    DecisionTimelineResponse,
    LineageNode,
)

VALID_STATUSES = frozenset({"active", "superseded", "reversed", "draft"})
VALID_CONFIDENCE = frozenset({"low", "medium", "high"})


class DecisionStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _conn(self):
        return psycopg2.connect(self.database_url)

    @staticmethod
    def _normalize_alternatives(value: Any) -> List[Dict[str, Any]]:
        alts = value or []
        if isinstance(alts, str):
            try:
                alts = json.loads(alts)
            except Exception:
                alts = []
        if not isinstance(alts, list):
            return []
        return alts

    @classmethod
    def _row_to_full(cls, row: Dict[str, Any]) -> DecisionFull:
        return DecisionFull(
            decision_id=str(row["decision_id"]),
            content_id=str(row["content_id"]) if row.get("content_id") else None,
            title=row["title"],
            decision_reason=row["decision_reason"],
            decision_context=row.get("decision_context"),
            why_this_matters=row.get("why_this_matters"),
            decision_status=row["decision_status"],
            reversible=row["reversible"],
            source_content_ids=[str(u) for u in (row.get("source_content_ids") or [])],
            linked_hub_ids=[str(u) for u in (row.get("linked_hub_ids") or [])],
            supersedes_decision_id=str(row["supersedes_decision_id"]) if row.get("supersedes_decision_id") else None,
            superseded_by_decision_id=str(row["superseded_by_decision_id"]) if row.get("superseded_by_decision_id") else None,
            alternatives_considered=cls._normalize_alternatives(row.get("alternatives_considered")),
            contradicting_evidence=row.get("contradicting_evidence"),
            confidence_level=row.get("confidence_level") or "medium",
            decision_tags=list(row.get("decision_tags") or []),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_summary(row: Dict[str, Any]) -> DecisionSummary:
        return DecisionSummary(
            decision_id=str(row["decision_id"]),
            title=row["title"],
            decision_status=row["decision_status"],
            reversible=row["reversible"],
            confidence_level=row.get("confidence_level") or "medium",
            decision_tags=list(row.get("decision_tags") or []),
            created_at=row["created_at"],
        )

    def list_conflicts(self, workspace_id: Optional[str] = None) -> DecisionConflictsResponse:
        ws_clause = "AND a.workspace_id = %s::uuid AND b.workspace_id = %s::uuid" if workspace_id else ""
        params: List[Any] = [workspace_id, workspace_id] if workspace_id else []
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        a.decision_id AS a_id, a.title AS a_title, a.decision_status AS a_status, a.created_at AS a_created,
                        b.decision_id AS b_id, b.title AS b_title, b.decision_status AS b_status, b.created_at AS b_created,
                        'Same hub_id: ' || h::text AS conflict_reason
                    FROM cb_decision_nodes a
                    JOIN cb_decision_nodes b ON a.decision_id < b.decision_id
                    JOIN LATERAL unnest(a.linked_hub_ids) h ON true
                    WHERE a.decision_status = 'active'
                      AND b.decision_status = 'active'
                      AND h = ANY(b.linked_hub_ids)
                      {ws_clause}
                    UNION ALL
                    SELECT
                        a.decision_id, a.title, a.decision_status, a.created_at,
                        b.decision_id, b.title, b.decision_status, b.created_at,
                        'Same tag: ' || t AS conflict_reason
                    FROM cb_decision_nodes a
                    JOIN cb_decision_nodes b ON a.decision_id < b.decision_id
                    JOIN LATERAL unnest(a.decision_tags) t ON true
                    WHERE a.decision_status = 'active'
                      AND b.decision_status = 'active'
                      AND t = ANY(b.decision_tags)
                      AND t != ''
                      {ws_clause}
                    """,
                    tuple(params + params),
                )
                rows = cur.fetchall()
        conflicts = [
            ConflictPair(
                decision_a=LineageNode(decision_id=str(r["a_id"]), title=r["a_title"], decision_status=r["a_status"], created_at=r["a_created"]),
                decision_b=LineageNode(decision_id=str(r["b_id"]), title=r["b_title"], decision_status=r["b_status"], created_at=r["b_created"]),
                conflict_reason=r["conflict_reason"],
            )
            for r in rows
        ]
        return DecisionConflictsResponse(conflicts=conflicts, count=len(conflicts))

    def get_timeline(self, hub_id: Optional[UUID], tags: Optional[str], limit: int, workspace_id: Optional[str] = None) -> DecisionTimelineResponse:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT decision_id, title, decision_status, reversible,
                           confidence_level, decision_tags, created_at
                      FROM cb_decision_nodes
                     WHERE (%s::uuid IS NULL OR workspace_id = %s::uuid)
                       AND (%s::uuid IS NULL OR %s::uuid = ANY(linked_hub_ids))
                       AND (%s::text[] IS NULL OR decision_tags && %s::text[])
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    (workspace_id, workspace_id, str(hub_id) if hub_id else None, str(hub_id) if hub_id else None, tag_list or None, tag_list or None, limit),
                )
                rows = cur.fetchall()
        grouped: Dict[str, List[DecisionSummary]] = {s: [] for s in VALID_STATUSES}
        for row in rows:
            grouped[row["decision_status"]].append(self._row_to_summary(row))
        return DecisionTimelineResponse(active=grouped["active"], superseded=grouped["superseded"], reversed=grouped["reversed"], draft=grouped["draft"], total=len(rows))

    def list_decisions(self, status: Optional[str], hub_id: Optional[UUID], limit: int, workspace_id: Optional[str] = None) -> DecisionListResponse:
        conditions: List[str] = []
        params: List[Any] = []
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        if status:
            conditions.append("decision_status = %s")
            params.append(status)
        if hub_id:
            conditions.append("%s::uuid = ANY(linked_hub_ids)")
            params.append(str(hub_id))
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT decision_id, title, decision_status, reversible,
                           confidence_level, decision_tags, created_at
                      FROM cb_decision_nodes
                    {where}
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    tuple(params + [limit]),
                )
                rows = cur.fetchall()
        return DecisionListResponse(decisions=[self._row_to_summary(r) for r in rows], count=len(rows))

    def create_decision(self, payload: DecisionCreate, workspace_id: Optional[str] = None, created_by_subject: Optional[str] = None) -> Dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if payload.supersedes_decision_id:
                    cur.execute(
                        "SELECT 1 FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid)",
                        (str(payload.supersedes_decision_id), workspace_id, workspace_id),
                    )
                    if not cur.fetchone():
                        raise KeyError(f"supersedes_decision_id {payload.supersedes_decision_id} not found")
                cur.execute(
                    """
                    INSERT INTO cb_decision_nodes (
                        workspace_id, title, decision_reason, decision_context, why_this_matters,
                        decision_status, reversible,
                        source_content_ids, linked_hub_ids,
                        supersedes_decision_id,
                        alternatives_considered, contradicting_evidence,
                        confidence_level, decision_tags, created_by_subject
                    ) VALUES (
                        %s::uuid, %s, %s, %s, %s, %s, %s,
                        %s::uuid[], %s::uuid[],
                        %s::uuid,
                        %s::jsonb, %s,
                        %s, %s::text[], %s
                    )
                    RETURNING decision_id::text AS decision_id, title, decision_status, created_at
                    """,
                    (workspace_id, payload.title, payload.decision_reason, payload.decision_context, payload.why_this_matters,
                     payload.decision_status, payload.reversible,
                     [str(u) for u in payload.source_content_ids] or None,
                     [str(u) for u in payload.linked_hub_ids] or None,
                     str(payload.supersedes_decision_id) if payload.supersedes_decision_id else None,
                     Json([a.model_dump() for a in payload.alternatives_considered] or []),
                     payload.contradicting_evidence, payload.confidence_level, payload.decision_tags or None, created_by_subject),
                )
                row = cur.fetchone()
                new_id = row["decision_id"]
                if payload.supersedes_decision_id:
                    cur.execute(
                        """
                        UPDATE cb_decision_nodes
                           SET superseded_by_decision_id = %s::uuid,
                               decision_status = 'superseded',
                               updated_at = NOW()
                         WHERE decision_id = %s::uuid
                           AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
                        """,
                        (new_id, str(payload.supersedes_decision_id), workspace_id, workspace_id),
                    )
            conn.commit()
        return row

    def get_lineage(self, decision_id: UUID, workspace_id: Optional[str] = None) -> DecisionLineageResponse:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT decision_id, title FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid)",
                    (str(decision_id), workspace_id, workspace_id),
                )
                base = cur.fetchone()
                if not base:
                    raise KeyError(f"Decision {decision_id} not found")
                cur.execute(
                    """
                    WITH RECURSIVE ancestors AS (
                        SELECT decision_id, title, decision_status, created_at, supersedes_decision_id, 1 AS depth
                          FROM cb_decision_nodes
                         WHERE decision_id = (SELECT supersedes_decision_id FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid))
                           AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
                        UNION ALL
                        SELECT d.decision_id, d.title, d.decision_status, d.created_at, d.supersedes_decision_id, a.depth + 1
                          FROM cb_decision_nodes d JOIN ancestors a ON d.decision_id = a.supersedes_decision_id
                         WHERE a.depth < 10 AND a.supersedes_decision_id IS NOT NULL
                           AND (%s::uuid IS NULL OR d.workspace_id = %s::uuid)
                    ), descendants AS (
                        SELECT decision_id, title, decision_status, created_at, superseded_by_decision_id, 1 AS depth
                          FROM cb_decision_nodes
                         WHERE decision_id = (SELECT superseded_by_decision_id FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid))
                           AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
                        UNION ALL
                        SELECT d.decision_id, d.title, d.decision_status, d.created_at, d.superseded_by_decision_id, desc2.depth + 1
                          FROM cb_decision_nodes d JOIN descendants desc2 ON d.decision_id = desc2.superseded_by_decision_id
                         WHERE desc2.depth < 10 AND desc2.superseded_by_decision_id IS NOT NULL
                           AND (%s::uuid IS NULL OR d.workspace_id = %s::uuid)
                    )
                    SELECT 'ancestor' AS role, decision_id, title, decision_status, created_at, depth FROM ancestors
                    UNION ALL
                    SELECT 'descendant' AS role, decision_id, title, decision_status, created_at, depth FROM descendants
                    ORDER BY role, depth
                    """,
                    (str(decision_id), workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id,
                     str(decision_id), workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id),
                )
                rows = cur.fetchall()
        ancestors = [LineageNode(decision_id=str(r["decision_id"]), title=r["title"], decision_status=r["decision_status"], created_at=r["created_at"]) for r in rows if r["role"] == "ancestor"]
        descendants = [LineageNode(decision_id=str(r["decision_id"]), title=r["title"], decision_status=r["decision_status"], created_at=r["created_at"]) for r in rows if r["role"] == "descendant"]
        max_depth = max((r["depth"] for r in rows), default=0)
        return DecisionLineageResponse(decision_id=str(base["decision_id"]), title=base["title"], ancestors=ancestors, descendants=descendants, depth=max_depth, depth_limit_reached=max_depth >= 10)

    def explain_decision(self, decision_id: UUID, workspace_id: Optional[str] = None) -> DecisionFull:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid)",
                    (str(decision_id), workspace_id, workspace_id),
                )
                row = cur.fetchone()
        if not row:
            raise KeyError(f"Decision {decision_id} not found")
        return self._row_to_full(row)

    def update_status(self, decision_id: UUID, decision_status: str, workspace_id: Optional[str] = None) -> DecisionFull:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE cb_decision_nodes
                       SET decision_status = %s, updated_at = NOW()
                     WHERE decision_id = %s::uuid
                       AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
                 RETURNING *
                    """,
                    (decision_status, str(decision_id), workspace_id, workspace_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise KeyError(f"Decision {decision_id} not found")
        return self._row_to_full(row)
