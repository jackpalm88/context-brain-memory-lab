"""HubEdgeStore — persistence for curated hub-to-hub relationships."""

import os
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

ALL_TYPES = {"parent", "related", "duplicate", "overlaps", "supports", "part_of", "contradicts"}
VALID_STATUSES = {"inferred", "manual", "approved", "rejected", "needs_review", "archived"}
VALID_ORIGINS = {"manual", "inferred_approved", "inferred_rejected", "ai_suggested", "migration_localStorage"}

_SELECT_COLS = """
    id::text, source_hub_id::text, target_hub_id::text,
    workspace_id::text AS workspace_id,
    type, status, origin, confidence, reason, note, weight, edge_key,
    created_by, created_at, updated_at, archived_at
"""


def _compute_edge_key(source_id: str, target_id: str, edge_type: str) -> str:
    a, b = sorted([source_id, target_id])
    return f"{a}|{b}|{edge_type}"


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    for ts_field in ("created_at", "updated_at", "archived_at"):
        if d.get(ts_field) is not None:
            d[ts_field] = d[ts_field].isoformat()
    return d


class HubEdgeStore:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not self.dsn:
            raise ValueError("DATABASE_URL not set")

    def _conn(self):
        return psycopg2.connect(self.dsn)

    def _validate_hubs_in_workspace(self, cur, source_hub_id: str, target_hub_id: str, workspace_id: Optional[str]) -> None:
        if not workspace_id:
            return
        cur.execute(
            """
            SELECT COUNT(*) AS c
              FROM cb_hubs
             WHERE hub_id IN (%s::uuid, %s::uuid)
               AND workspace_uuid = %s::uuid
            """,
            (source_hub_id, target_hub_id, workspace_id),
        )
        if cur.fetchone()["c"] != 2:
            raise KeyError("source/target hub not found in workspace")

    def create_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        status: str = "manual",
        origin: str = "manual",
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        weight: Optional[float] = None,
        created_by: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if edge_type not in ALL_TYPES:
            raise ValueError(f"Invalid type '{edge_type}'. Must be one of: {sorted(ALL_TYPES)}")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'")
        if origin not in VALID_ORIGINS:
            raise ValueError(f"Invalid origin '{origin}'")
        edge_key = _compute_edge_key(source_hub_id, target_hub_id, edge_type)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                self._validate_hubs_in_workspace(cur, source_hub_id, target_hub_id, workspace_id)
                try:
                    cur.execute(
                        f"""
                        INSERT INTO cb_hub_edges
                            (source_hub_id, target_hub_id, workspace_id, type, status, origin,
                             confidence, reason, note, weight, edge_key, created_by)
                        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {_SELECT_COLS}
                        """,
                        (source_hub_id, target_hub_id, workspace_id, edge_type, status, origin,
                         confidence, reason, note, weight, edge_key, created_by),
                    )
                    conn.commit()
                    return _row_to_dict(cur.fetchone())
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    raise ValueError(f"Active edge already exists for key '{edge_key}'. Archive the existing edge before creating a new one.")

    def get_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["id = %s::uuid"]
        params: List[Any] = [edge_id]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT {_SELECT_COLS} FROM cb_hub_edges WHERE {' AND '.join(conditions)}", tuple(params))
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def list_edges(
        self,
        hub_id: Optional[str] = None,
        include_rejected: bool = False,
        include_archived: bool = False,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conditions = []
        params: List[Any] = []
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        if hub_id:
            conditions.append("(source_hub_id = %s::uuid OR target_hub_id = %s::uuid)")
            params.extend([hub_id, hub_id])
        if not include_archived:
            conditions.append("archived_at IS NULL")
        if not include_rejected:
            conditions.append("status != 'rejected'")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT {_SELECT_COLS} FROM cb_hub_edges {where} ORDER BY created_at DESC", tuple(params))
                return [_row_to_dict(r) for r in cur.fetchall()]

    def update_edge(self, edge_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {"type", "status", "note", "reason", "confidence"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return self.get_edge(edge_id)
        if "type" in fields and fields["type"] not in ALL_TYPES:
            raise ValueError(f"Invalid type '{fields['type']}'")
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{fields['status']}'")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [edge_id]
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE cb_hub_edges
                    SET {set_clause}, updated_at = NOW()
                    WHERE id = %s::uuid
                    RETURNING {_SELECT_COLS}
                    """,
                    values,
                )
                conn.commit()
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def archive_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["id = %s::uuid", "archived_at IS NULL"]
        params: List[Any] = [edge_id]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE cb_hub_edges
                    SET archived_at = NOW(), status = 'archived', updated_at = NOW()
                    WHERE {' AND '.join(conditions)}
                    RETURNING {_SELECT_COLS}
                    """,
                    tuple(params),
                )
                conn.commit()
                row = cur.fetchone()
                return _row_to_dict(row) if row else None

    def approve_inferred_edge(self, source_hub_id: str, target_hub_id: str, edge_type: str,
                              reason: Optional[str] = None, confidence: Optional[float] = None,
                              note: Optional[str] = None, created_by: str = "user") -> Dict[str, Any]:
        edge_key = _compute_edge_key(source_hub_id, target_hub_id, edge_type)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    INSERT INTO cb_hub_edges
                        (source_hub_id, target_hub_id, type, status, origin,
                         confidence, reason, note, edge_key, created_by)
                    VALUES (%s::uuid, %s::uuid, %s, 'approved', 'inferred_approved', %s, %s, %s, %s, %s)
                    ON CONFLICT (edge_key) WHERE archived_at IS NULL
                    DO UPDATE SET status = 'approved', origin = 'inferred_approved', confidence = EXCLUDED.confidence,
                        reason = COALESCE(EXCLUDED.reason, cb_hub_edges.reason),
                        note = COALESCE(EXCLUDED.note, cb_hub_edges.note), updated_at = NOW()
                    RETURNING {_SELECT_COLS}
                    """,
                    (source_hub_id, target_hub_id, edge_type, confidence, reason, note, edge_key, created_by),
                )
                conn.commit()
                return _row_to_dict(cur.fetchone())

    def reject_inferred_edge(self, source_hub_id: str, target_hub_id: str, edge_type: str,
                             reason: Optional[str] = None, note: Optional[str] = None,
                             created_by: str = "user") -> Dict[str, Any]:
        edge_key = _compute_edge_key(source_hub_id, target_hub_id, edge_type)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    INSERT INTO cb_hub_edges
                        (source_hub_id, target_hub_id, type, status, origin, reason, note, edge_key, created_by)
                    VALUES (%s::uuid, %s::uuid, %s, 'rejected', 'inferred_rejected', %s, %s, %s, %s)
                    ON CONFLICT (edge_key) WHERE archived_at IS NULL
                    DO UPDATE SET status = 'rejected', origin = 'inferred_rejected',
                        reason = COALESCE(EXCLUDED.reason, cb_hub_edges.reason),
                        note = COALESCE(EXCLUDED.note, cb_hub_edges.note), updated_at = NOW()
                    RETURNING {_SELECT_COLS}
                    """,
                    (source_hub_id, target_hub_id, edge_type, reason, note, edge_key, created_by),
                )
                conn.commit()
                return _row_to_dict(cur.fetchone())
