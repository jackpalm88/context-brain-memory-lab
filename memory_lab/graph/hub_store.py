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
        owner_defined: bool = True,
    ) -> Dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO cb_hubs
                        (title, type, description, aliases, related_terms, workspace_id, owner_defined)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING hub_id::text, title, type, description, aliases, related_terms,
                              status, owner_defined, workspace_id, created_at, updated_at
                    """,
                    (title, type, description, aliases or [], related_terms or [], workspace_id, owner_defined),
                )
                conn.commit()
                return dict(cur.fetchone())

    def get_hub(self, hub_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT h.hub_id::text, h.title, h.type, h.description, h.aliases, h.related_terms,
                           h.status, h.owner_defined, h.workspace_id, h.created_at, h.updated_at,
                           COALESCE(ARRAY_AGG(hc.content_id) FILTER (WHERE hc.content_id IS NOT NULL), '{}') AS linked_content_ids
                    FROM cb_hubs h
                    LEFT JOIN cb_hub_content hc ON hc.hub_id = h.hub_id
                    WHERE h.hub_id = %s::uuid
                    GROUP BY h.hub_id
                    """,
                    (hub_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update_hub(self, hub_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {"title", "type", "description", "aliases", "related_terms", "status"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return self.get_hub(hub_id)
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [hub_id]
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE cb_hubs SET {set_clause}, updated_at = NOW()
                    WHERE hub_id = %s::uuid
                    RETURNING hub_id::text, title, type, description, aliases, related_terms,
                              status, owner_defined, workspace_id, created_at, updated_at
                    """,
                    values,
                )
                conn.commit()
                row = cur.fetchone()
                return dict(row) if row else None

    def list_hubs(
        self, workspace_id: Optional[str] = None, status: str = "active"
    ) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if workspace_id is not None:
                    cur.execute(
                        """
                        SELECT hub_id::text, title, type, description, aliases, related_terms,
                               status, owner_defined, workspace_id, created_at, updated_at
                        FROM cb_hubs WHERE status = %s AND workspace_id = %s
                        ORDER BY created_at DESC
                        """,
                        (status, workspace_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT hub_id::text, title, type, description, aliases, related_terms,
                               status, owner_defined, workspace_id, created_at, updated_at
                        FROM cb_hubs WHERE status = %s
                        ORDER BY created_at DESC
                        """,
                        (status,),
                    )
                return [dict(r) for r in cur.fetchall()]

    def link_content(self, hub_id: str, content_id: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cb_hub_content (hub_id, content_id)
                    VALUES (%s::uuid, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (hub_id, content_id),
                )
                conn.commit()
                return True

    def get_hub_content_ids(self, hub_id: str) -> List[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content_id FROM cb_hub_content WHERE hub_id = %s::uuid",
                    (hub_id,),
                )
                return [r[0] for r in cur.fetchall()]

    def match_query(self, query: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Match query to an active hub. Priority order:
          1. Exact title match
          2. Exact alias match
          3. Alias is a substring of the query (min 6 chars — spec §8 fuzzy match)
          4. Exact related_term match
        workspace_id scopes the search but falls back to global hubs (workspace_id IS NULL).
        """
        q = query.strip().lower()
        ws_clause = "AND (workspace_id = %s OR workspace_id IS NULL)" if workspace_id else ""

        def _params(base: list) -> list:
            return base + ([workspace_id] if workspace_id else [])

        select = """
            SELECT hub_id::text, title, aliases, related_terms
            FROM cb_hubs WHERE status = 'active'
        """

        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Exact title match
                cur.execute(f"{select} AND LOWER(title) = %s {ws_clause} LIMIT 1", _params([q]))
                row = cur.fetchone()
                if row:
                    return dict(row)

                # 2. Any alias exact match
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

                # 3a. Alias substring: long alias (6+ chars) appears as substring in query
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

                # 3b. Short alias (3–5 chars) matched as a whole word in query (word-boundary)
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

                # 4. Any related_term exact match
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
