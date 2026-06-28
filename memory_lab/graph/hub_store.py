import os
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


class HubStore:
    """Sync PostgreSQL-backed hub store. Wrap calls with run_in_threadpool in async context."""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not self.dsn:
            raise ValueError("DATABASE_URL not set")

    def _conn(self):
        return psycopg2.connect(self.dsn)

    def create_hub(
        self,
        title: str,
        type: str = "topic",
        description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        related_terms: Optional[List[str]] = None,
        workspace_id: Optional[str] = None,
        workspace_uuid: Optional[str] = None,
        owner_defined: bool = True,
        created_by_subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO cb_hubs
                        (title, type, description, aliases, related_terms, workspace_id, workspace_uuid, owner_defined, created_by_subject)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::uuid, %s, %s)
                    RETURNING hub_id::text, title, type, description, aliases, related_terms,
                              status, owner_defined, workspace_id, workspace_uuid::text AS workspace_uuid,
                              created_at, updated_at
                    """,
                    (title, type, description, aliases or [], related_terms or [], workspace_id, workspace_uuid, owner_defined, created_by_subject),
                )
                conn.commit()
                return dict(cur.fetchone())

    def get_hub(self, hub_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["h.hub_id = %s::uuid"]
        params: List[Any] = [hub_id]
        if workspace_id:
            conditions.append("h.workspace_uuid = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT h.hub_id::text, h.title, h.type, h.description, h.aliases, h.related_terms,
                           h.status, h.owner_defined, h.workspace_id, h.workspace_uuid::text AS workspace_uuid,
                           h.created_by_subject, h.created_at, h.updated_at,
                           COALESCE(ARRAY_AGG(hc.content_id) FILTER (WHERE hc.content_id IS NOT NULL), '{{}}') AS linked_content_ids
                    FROM cb_hubs h
                    LEFT JOIN cb_hub_content hc ON hc.hub_id = h.hub_id
                    WHERE {' AND '.join(conditions)}
                    GROUP BY h.hub_id
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update_hub(self, hub_id: str, updates: Dict[str, Any], workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        allowed = {"title", "type", "description", "aliases", "related_terms", "status"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return self.get_hub(hub_id, workspace_id=workspace_id)
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        ws_clause = "AND workspace_uuid = %s::uuid" if workspace_id else ""
        values = list(fields.values()) + [hub_id]
        if workspace_id:
            values.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE cb_hubs SET {set_clause}, updated_at = NOW()
                    WHERE hub_id = %s::uuid {ws_clause}
                    RETURNING hub_id::text, title, type, description, aliases, related_terms,
                              status, owner_defined, workspace_id, workspace_uuid::text AS workspace_uuid,
                              created_at, updated_at
                    """,
                    values,
                )
                conn.commit()
                row = cur.fetchone()
                return dict(row) if row else None

    def list_hubs(self, workspace_id: Optional[str] = None, status: str = "active") -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if workspace_id is not None:
                    cur.execute(
                        """
                        SELECT hub_id::text, title, type, description, aliases, related_terms,
                               status, owner_defined, workspace_id, workspace_uuid::text AS workspace_uuid,
                               created_at, updated_at
                        FROM cb_hubs WHERE status = %s AND workspace_uuid = %s::uuid
                        ORDER BY created_at DESC
                        """,
                        (status, workspace_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT hub_id::text, title, type, description, aliases, related_terms,
                               status, owner_defined, workspace_id, workspace_uuid::text AS workspace_uuid,
                               created_at, updated_at
                        FROM cb_hubs WHERE status = %s
                        ORDER BY created_at DESC
                        """,
                        (status,),
                    )
                return [dict(r) for r in cur.fetchall()]

    def link_content(self, hub_id: str, content_id: str, workspace_id: Optional[str] = None, created_by_subject: Optional[str] = None) -> bool:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if workspace_id:
                    cur.execute(
                        "SELECT hub_id::text FROM cb_hubs WHERE hub_id = %s::uuid AND workspace_uuid = %s::uuid",
                        (hub_id, workspace_id),
                    )
                    if not cur.fetchone():
                        raise KeyError("hub not found in workspace")
                    cur.execute(
                        "SELECT content_id::text FROM content_items WHERE content_id = %s::uuid AND workspace_id = %s::uuid",
                        (content_id, workspace_id),
                    )
                    if not cur.fetchone():
                        raise KeyError("content not found in workspace")
                cur.execute(
                    """
                    INSERT INTO cb_hub_content (hub_id, content_id, workspace_id, created_by_subject)
                    VALUES (%s::uuid, %s::uuid, %s::uuid, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (hub_id, content_id, workspace_id, created_by_subject),
                )
                conn.commit()
                return True

    def get_hub_content_ids(self, hub_id: str, workspace_id: Optional[str] = None) -> List[str]:
        conditions = ["hc.hub_id = %s::uuid"]
        params: List[Any] = [hub_id]
        if workspace_id:
            conditions.append("hc.workspace_id = %s::uuid")
            conditions.append("ci.workspace_id = %s::uuid")
            params.extend([workspace_id, workspace_id])
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT hc.content_id
                    FROM cb_hub_content hc
                    JOIN content_items ci ON ci.content_id = hc.content_id::uuid
                    WHERE {' AND '.join(conditions)}
                    """,
                    tuple(params),
                )
                return [r[0] for r in cur.fetchall()]

    def match_query(self, query: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        q = query.strip().lower()
        ws_clause = "AND (workspace_uuid = %s::uuid OR workspace_uuid IS NULL)" if workspace_id else ""

        def _params(base: list) -> list:
            return base + ([workspace_id] if workspace_id else [])

        select = """
            SELECT hub_id::text, title, aliases, related_terms
            FROM cb_hubs WHERE status = 'active'
        """
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"{select} AND LOWER(title) = %s {ws_clause} LIMIT 1", _params([q]))
                row = cur.fetchone()
                if row:
                    return dict(row)
                cur.execute(
                    f"""
                    {select}
                    AND EXISTS (SELECT 1 FROM unnest(aliases) a WHERE LOWER(a) = %s)
                    {ws_clause} LIMIT 1
                    """,
                    _params([q]),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
                cur.execute(
                    f"""
                    {select}
                    AND EXISTS (
                        SELECT 1 FROM unnest(aliases) a
                        WHERE LENGTH(a) >= 6
                          AND %s LIKE CONCAT('%%', LOWER(a), '%%')
                    )
                    {ws_clause} LIMIT 1
                    """,
                    _params([q]),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
                cur.execute(
                    f"""
                    {select}
                    AND EXISTS (
                        SELECT 1 FROM unnest(aliases) a
                        WHERE LENGTH(a) BETWEEN 3 AND 5
                          AND %s ~ CONCAT('(^|[^a-z0-9])', LOWER(a), '([^a-z0-9]|$)')
                    )
                    {ws_clause} LIMIT 1
                    """,
                    _params([q]),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
                cur.execute(
                    f"""
                    {select}
                    AND EXISTS (SELECT 1 FROM unnest(related_terms) t WHERE LOWER(t) = %s)
                    {ws_clause} LIMIT 1
                    """,
                    _params([q]),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
        return None
