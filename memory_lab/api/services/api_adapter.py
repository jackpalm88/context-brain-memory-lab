from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.graph.hub_store import HubStore
from memory_lab.graph.hub_edge_store import HubEdgeStore
from memory_lab.ingestion.scorer import score_content
from memory_lab.governance.tier_router import route as tier_route


class ApiAdapter:
    """Thin adapter over PR1a stores. No runtime side-effects beyond normal store calls."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.hub_store = HubStore(database_url)
        self.hub_edge_store = HubEdgeStore(database_url)

    def _conn(self):
        return psycopg2.connect(self.database_url)

    @staticmethod
    def _workspace_meta(workspace_id: Optional[str], source: Optional[str] = None) -> Dict[str, Any]:
        if not workspace_id:
            return {}
        meta: Dict[str, Any] = {"workspace_id": workspace_id}
        if source:
            meta["workspace_context_source"] = source
        return meta

    def create_content_minimal(
        self,
        content: Optional[str] = None,
        workspace_id: Optional[str] = None,
        workspace_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO content_items (workspace_id)
                    VALUES (%s::uuid)
                    RETURNING content_id::text AS content_id
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                conn.commit()

        event = score_content(content or "")
        tier_decision = tier_route(
            composite_score=event.scores.composite,
            circuit_open=event.circuit_open,
            quality_score=event.scores.quality,
        )
        tier = tier_decision.tier
        tier_reason = tier_decision.reason

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE content_items
                       SET quality_score    = %s,
                           relevance_score  = %s,
                           novelty_score    = %s,
                           composite_score  = %s,
                           score_confidence = %s,
                           circuit_open     = %s,
                           tier             = %s::memory_tier,
                           tier_assigned_at = NOW(),
                           tier_reason      = %s
                     WHERE content_id = %s::uuid
                    """,
                    (
                        event.scores.quality,
                        event.scores.relevance,
                        event.scores.novelty,
                        event.scores.composite,
                        0.0,
                        event.circuit_open,
                        tier,
                        tier_reason,
                        row["content_id"],
                    ),
                )
                conn.commit()

        if event.fallback_reason:
            governance_lines = [
                f"score:fallback composite={event.scores.composite} reason={event.fallback_reason}",
                f"tier:{tier} tier_reason:{tier_reason}",
            ]
        else:
            governance_lines = [
                f"score:quality={event.scores.quality} relevance={event.scores.relevance} novelty={event.scores.novelty} composite={event.scores.composite}",
                f"tier:{tier} tier_reason:{tier_reason}",
            ]

        response = {
            "content_id": row["content_id"],
            "created": True,
            "mode": "governed_fallback" if event.fallback_reason else "governed",
            "scores": {
                "quality": event.scores.quality,
                "relevance": event.scores.relevance,
                "novelty": event.scores.novelty,
                "composite": event.scores.composite,
            },
            "tier": tier,
            "tier_reason": tier_reason,
            "fallback_reason": event.fallback_reason,
            "governance_lines": governance_lines,
        }
        response.update(self._workspace_meta(workspace_id, workspace_source))
        return response

    def get_content_minimal(self, content_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["content_id = %s::uuid"]
        params: List[Any] = [content_id]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT content_id::text AS content_id,
                           workspace_id::text AS workspace_id,
                           created_at, updated_at,
                           tier::text AS tier,
                           tier_assigned_at,
                           tier_reason,
                           quality_score,
                           relevance_score,
                           novelty_score,
                           composite_score,
                           score_confidence,
                           circuit_open,
                           retrieval_count,
                           last_retrieved_at
                      FROM content_items
                     WHERE {' AND '.join(conditions)}
                    """,
                    tuple(params),
                )
                row = cur.fetchone()

        if not row:
            return None

        def _iso(v):
            return v.isoformat() if v else None

        return {
            "content_id": row["content_id"],
            "workspace_id": row.get("workspace_id"),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
            "tier": row.get("tier"),
            "tier_assigned_at": _iso(row.get("tier_assigned_at")),
            "tier_reason": row.get("tier_reason"),
            "quality_score": row.get("quality_score"),
            "relevance_score": row.get("relevance_score"),
            "novelty_score": row.get("novelty_score"),
            "composite_score": row.get("composite_score"),
            "score_confidence": row.get("score_confidence"),
            "circuit_open": row.get("circuit_open"),
            "retrieval_count": row.get("retrieval_count"),
            "last_retrieved_at": _iso(row.get("last_retrieved_at")),
        }

    def create_hub(self, payload: Dict[str, Any], workspace_id: Optional[str] = None, workspace_source: Optional[str] = None) -> Dict[str, Any]:
        hub = self.hub_store.create_hub(
            title=payload["title"],
            type=payload.get("hub_type", "topic"),
            description=payload.get("description"),
            aliases=payload.get("aliases") or [],
            related_terms=payload.get("related_terms") or [],
            workspace_uuid=workspace_id,
        )
        hub.update(self._workspace_meta(workspace_id, workspace_source))
        return hub

    def get_hub(self, hub_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_store.get_hub(hub_id, workspace_id=workspace_id)

    def link_content(self, hub_id: str, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        self.hub_store.link_content(hub_id, content_id, workspace_id=workspace_id)
        result = {"hub_id": hub_id, "content_id": content_id, "linked": True}
        if workspace_id:
            result["workspace_id"] = workspace_id
        return result

    def create_edge(self, payload: Dict[str, Any], workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self.hub_edge_store.create_edge(
            source_hub_id=payload["source_hub_id"],
            target_hub_id=payload["target_hub_id"],
            edge_type=payload["edge_type"],
            status=payload.get("status", "manual"),
            origin=payload.get("origin", "manual"),
            confidence=payload.get("confidence"),
            reason=payload.get("reason"),
            note=payload.get("note"),
            workspace_id=workspace_id,
        )

    def get_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.get_edge(edge_id, workspace_id=workspace_id)

    def list_edges(self, hub_id: Optional[str], include_archived: bool, include_rejected: bool, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.hub_edge_store.list_edges(
            hub_id=hub_id,
            include_archived=include_archived,
            include_rejected=include_rejected,
            workspace_id=workspace_id,
        )

    def archive_edge(self, edge_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.archive_edge(edge_id, workspace_id=workspace_id)
