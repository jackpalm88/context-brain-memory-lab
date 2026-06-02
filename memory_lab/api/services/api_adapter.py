from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.graph.hub_store import HubStore
from memory_lab.graph.hub_edge_store import HubEdgeStore


class ApiAdapter:
    """Thin adapter over PR1a stores. No runtime side-effects beyond normal store calls."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.hub_store = HubStore(database_url)
        self.hub_edge_store = HubEdgeStore(database_url)

    def _conn(self):
        return psycopg2.connect(self.database_url)

    # Content: schema-safe minimal mode only (ID allocation only)
    def create_content_minimal(self, content: Optional[str] = None) -> Dict[str, Any]:
        # Intentionally does not persist content body and does not write content_chunks.
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO content_items DEFAULT VALUES
                    RETURNING content_id::text AS content_id
                    """
                )
                row = cur.fetchone()
                conn.commit()

        return {
            "content_id": row["content_id"],
            "created": True,
            "mode": "id_allocation_only",
            "body_persistence": "not_supported_in_this_mode",
        }

    def get_content_minimal(self, content_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT content_id::text AS content_id, created_at, updated_at
                    FROM content_items
                    WHERE content_id = %s::uuid
                    """,
                    (content_id,),
                )
                row = cur.fetchone()

        if not row:
            return None

        return {
            "content_id": row["content_id"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            "mode": "id_allocation_only",
        }

    def create_hub(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        hub = self.hub_store.create_hub(
            title=payload["title"],
            type=payload.get("hub_type", "topic"),
            description=payload.get("description"),
            aliases=payload.get("aliases") or [],
            related_terms=payload.get("related_terms") or [],
        )
        return hub

    def get_hub(self, hub_id: str) -> Optional[Dict[str, Any]]:
        return self.hub_store.get_hub(hub_id)

    def link_content(self, hub_id: str, content_id: str) -> Dict[str, Any]:
        self.hub_store.link_content(hub_id, content_id)
        return {"hub_id": hub_id, "content_id": content_id, "linked": True}

    def create_edge(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.hub_edge_store.create_edge(
            source_hub_id=payload["source_hub_id"],
            target_hub_id=payload["target_hub_id"],
            edge_type=payload["edge_type"],
            status=payload.get("status", "manual"),
            origin=payload.get("origin", "manual"),
            confidence=payload.get("confidence"),
            reason=payload.get("reason"),
            note=payload.get("note"),
        )

    def get_edge(self, edge_id: str) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.get_edge(edge_id)

    def list_edges(self, hub_id: Optional[str], include_archived: bool, include_rejected: bool) -> List[Dict[str, Any]]:
        return self.hub_edge_store.list_edges(
            hub_id=hub_id,
            include_archived=include_archived,
            include_rejected=include_rejected,
        )

    def archive_edge(self, edge_id: str) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.archive_edge(edge_id)
