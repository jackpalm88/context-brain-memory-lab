import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Set, Optional

from .edge import Edge


class GraphStore:
    """Sync PostgreSQL-backed edge store. Use run_in_threadpool when calling from async context."""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not self.dsn:
            raise ValueError("DATABASE_URL not set and no dsn provided")

    def _conn(self):
        return psycopg2.connect(self.dsn)

    def add_edge(self, edge: Edge, workspace_id: Optional[str] = None) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cb_edges (from_node, relation, to_node, source_id, confidence, workspace_id)
                    VALUES (%s, %s, %s, %s, %s, %s::uuid)
                    ON CONFLICT (from_node, relation, to_node, source_id) DO UPDATE
                    SET confidence = EXCLUDED.confidence,
                        workspace_id = COALESCE(EXCLUDED.workspace_id, cb_edges.workspace_id),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (edge.from_node, edge.relation, edge.to_node, edge.source_id, edge.confidence, workspace_id),
                )
                conn.commit()
                return cur.fetchone()[0]

    def add_edges(self, edges: List[Edge], workspace_id: Optional[str] = None) -> List[int]:
        return [self.add_edge(e, workspace_id=workspace_id) for e in edges]

    def get_neighbors(self, node: str, min_confidence: float = 0.7, workspace_id: Optional[str] = None) -> Set[str]:
        conditions = ["(LOWER(from_node) = LOWER(%s) OR LOWER(to_node) = LOWER(%s))", "confidence >= %s"]
        params = [node, node, min_confidence]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT from_node, to_node FROM cb_edges
                    WHERE {' AND '.join(conditions)}
                    """,
                    tuple(params),
                )
                neighbors: Set[str] = set()
                for a, b in cur.fetchall():
                    neighbors.add(b if a.lower() == node.lower() else a)
                return neighbors

    def get_edges_for_node(self, node: str, min_confidence: float = 0.7, workspace_id: Optional[str] = None) -> List[Edge]:
        conditions = ["(LOWER(from_node) = LOWER(%s) OR LOWER(to_node) = LOWER(%s))", "confidence >= %s"]
        params = [node, node, min_confidence]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT from_node, relation, to_node, source_id, confidence
                    FROM cb_edges
                    WHERE {' AND '.join(conditions)}
                    ORDER BY confidence DESC
                    """,
                    tuple(params),
                )
                return [Edge(**row) for row in cur.fetchall()]

    def delete_edges_for_source(self, source_id: str) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cb_edges WHERE source_id = %s RETURNING id",
                    (source_id,),
                )
                conn.commit()
                return len(cur.fetchall())
