from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID
import json

import psycopg2
from psycopg2.extras import Json, RealDictCursor, register_uuid

from .models import (
    ConflictPair,
    DecisionConflictsResponse,
    DecisionContentLink,
    DecisionCreate,
    DecisionFull,
    DecisionLineageResponse,
    DecisionListResponse,
    DecisionsByContentResponse,
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
        conn = psycopg2.connect(self.database_url)
        # Without the UUID casters, psycopg2 hands uuid[] columns back as their
        # raw '{...}' literal string, which _row_to_full then iterates
        # character-by-character. Scoped to this connection so stores that
        # expect plain-str uuid columns are untouched.
        register_uuid(conn_or_curs=conn)
        return conn

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
            created_by_subject=row.get("created_by_subject"),
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
            created_by_subject=row.get("created_by_subject"),
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
                        a.decision_id AS a_id, a.title AS a_title, a.decision_status AS a_status, a.created_at AS a_created, a.created_by_subject AS a_created_by,
                        b.decision_id AS b_id, b.title AS b_title, b.decision_status AS b_status, b.created_at AS b_created, b.created_by_subject AS b_created_by,
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
                        a.decision_id, a.title, a.decision_status, a.created_at, a.created_by_subject,
                        b.decision_id, b.title, b.decision_status, b.created_at, b.created_by_subject,
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
                decision_a=LineageNode(decision_id=str(r["a_id"]), title=r["a_title"], decision_status=r["a_status"], created_by_subject=r.get("a_created_by"), created_at=r["a_created"]),
                decision_b=LineageNode(decision_id=str(r["b_id"]), title=r["b_title"], decision_status=r["b_status"], created_by_subject=r.get("b_created_by"), created_at=r["b_created"]),
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
                           confidence_level, decision_tags, created_by_subject, created_at
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
        flat = [self._row_to_summary(row) for row in rows]  # already newest-first
        grouped: Dict[str, List[DecisionSummary]] = {s: [] for s in VALID_STATUSES}
        for summary in flat:
            grouped[summary.decision_status].append(summary)
        # CF-001 additive completion: the same rows flat (decisions) with a
        # conventional count, ALONGSIDE the status buckets — never instead.
        return DecisionTimelineResponse(
            active=grouped["active"], superseded=grouped["superseded"],
            reversed=grouped["reversed"], draft=grouped["draft"],
            total=len(flat), decisions=flat, count=len(flat),
        )

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
                           confidence_level, decision_tags, created_by_subject, created_at
                      FROM cb_decision_nodes
                    {where}
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    tuple(params + [limit]),
                )
                rows = cur.fetchall()
        return DecisionListResponse(decisions=[self._row_to_summary(r) for r in rows], count=len(rows))

    def list_decisions_for_content(
        self, content_id: UUID, limit: int = 50, workspace_id: Optional[str] = None
    ) -> DecisionsByContentResponse:
        """CF-002 Stage 1: the derived content→decision reverse read.

        Matches the two existing link columns (canonical content_id OR
        membership in source_content_ids) — no denormalized backlink exists or
        is wanted. Unknown/foreign content ids yield count=0, never 404: "which
        decisions reference X" has the honest answer "none" without leaking
        whether X exists.
        """
        conditions = ["(content_id = %s::uuid OR %s::uuid = ANY(source_content_ids))"]
        params: List[Any] = [str(content_id), str(content_id)]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT decision_id, title, decision_status, reversible,
                           confidence_level, decision_tags, created_by_subject, created_at,
                           (content_id = %s::uuid) AS is_canonical,
                           (%s::uuid = ANY(source_content_ids)) AS is_source
                      FROM cb_decision_nodes
                     WHERE {' AND '.join(conditions)}
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    tuple([str(content_id), str(content_id)] + params + [limit]),
                )
                rows = cur.fetchall()
        links = [
            DecisionContentLink(
                **self._row_to_summary(row).model_dump(),
                link_role="canonical" if row.get("is_canonical") else "source",
                also_source=bool(row.get("is_canonical") and row.get("is_source")),
            )
            for row in rows
        ]
        return DecisionsByContentResponse(
            decisions=links, count=len(links),
            content_id=str(content_id), workspace_id=workspace_id,
        )

    def search_preview(
        self, query: str, limit: int, hub_id: Optional[str] = None, workspace_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Free-text preview search over cb_decision_nodes for search_graph_preview's
        node_type="decision" branch. cb_decision_nodes is a separate table from
        content_items/content_chunks — this exists so that branch can see the real
        decision corpus instead of only the content_items.node_type='decision'
        classification flag, which is a different, largely-unused concept.
        """
        q = f"%{(query or '').lower()}%"
        params: List[Any] = []
        hub_match_expr = "FALSE AS hub_match"
        if hub_id:
            hub_match_expr = "(%s::uuid = ANY(linked_hub_ids)) AS hub_match"
            params.append(hub_id)
        params.append(q)
        conditions = [
            "(LOWER(title) LIKE %s OR LOWER(decision_reason) LIKE %s "
            "OR LOWER(COALESCE(decision_context, '')) LIKE %s OR LOWER(COALESCE(why_this_matters, '')) LIKE %s)"
        ]
        params.extend([q, q, q, q])
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT decision_id::text AS decision_id,
                           title,
                           decision_reason,
                           {hub_match_expr},
                           CASE WHEN LOWER(title) LIKE %s THEN 2 ELSE 1 END AS score
                      FROM cb_decision_nodes
                     WHERE {' AND '.join(conditions)}
                     ORDER BY score DESC, decision_id
                     LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

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
                        SELECT decision_id, title, decision_status, created_at, created_by_subject, supersedes_decision_id, 1 AS depth
                          FROM cb_decision_nodes
                         WHERE decision_id = (SELECT supersedes_decision_id FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid))
                           AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
                        UNION ALL
                        SELECT d.decision_id, d.title, d.decision_status, d.created_at, d.created_by_subject, d.supersedes_decision_id, a.depth + 1
                          FROM cb_decision_nodes d JOIN ancestors a ON d.decision_id = a.supersedes_decision_id
                         WHERE a.depth < 10 AND a.supersedes_decision_id IS NOT NULL
                           AND (%s::uuid IS NULL OR d.workspace_id = %s::uuid)
                    ), descendants AS (
                        SELECT decision_id, title, decision_status, created_at, created_by_subject, superseded_by_decision_id, 1 AS depth
                          FROM cb_decision_nodes
                         WHERE decision_id = (SELECT superseded_by_decision_id FROM cb_decision_nodes WHERE decision_id = %s::uuid AND (%s::uuid IS NULL OR workspace_id = %s::uuid))
                           AND (%s::uuid IS NULL OR workspace_id = %s::uuid)
                        UNION ALL
                        SELECT d.decision_id, d.title, d.decision_status, d.created_at, d.created_by_subject, d.superseded_by_decision_id, desc2.depth + 1
                          FROM cb_decision_nodes d JOIN descendants desc2 ON d.decision_id = desc2.superseded_by_decision_id
                         WHERE desc2.depth < 10 AND desc2.superseded_by_decision_id IS NOT NULL
                           AND (%s::uuid IS NULL OR d.workspace_id = %s::uuid)
                    )
                    SELECT 'ancestor' AS role, decision_id, title, decision_status, created_at, created_by_subject, depth FROM ancestors
                    UNION ALL
                    SELECT 'descendant' AS role, decision_id, title, decision_status, created_at, created_by_subject, depth FROM descendants
                    ORDER BY role, depth
                    """,
                    (str(decision_id), workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id,
                     str(decision_id), workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id),
                )
                rows = cur.fetchall()
        ancestors = [LineageNode(decision_id=str(r["decision_id"]), title=r["title"], decision_status=r["decision_status"], created_by_subject=r.get("created_by_subject"), created_at=r["created_at"]) for r in rows if r["role"] == "ancestor"]
        descendants = [LineageNode(decision_id=str(r["decision_id"]), title=r["title"], decision_status=r["decision_status"], created_by_subject=r.get("created_by_subject"), created_at=r["created_at"]) for r in rows if r["role"] == "descendant"]
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
