from typing import Any, Dict, List, Callable, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.graph.adapter import CBGraphAdapter
from memory_lab.graph.hub_store import HubStore
from memory_lab.graph.store import GraphStore


class RetrievalAdapter:
    """Provider-neutral retrieval adapter with deterministic workspace-scoped DB defaults."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.graph_store = GraphStore(database_url)
        self.hub_store = HubStore(database_url)
        self.vector_search_fn: Callable[[str], List[Dict[str, Any]]] = self._deterministic_vector_search
        self.rerank_fn: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]] = self._deterministic_rerank
        self.adapter = CBGraphAdapter(
            graph_store=self.graph_store,
            vector_search_fn=self.vector_search_fn,
            rerank_fn=self.rerank_fn,
        )

    def _conn(self):
        return psycopg2.connect(self.database_url)

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        return [t.strip().lower() for t in query.split() if len(t.strip()) >= 3][:8]

    def _deterministic_vector_search(self, query: str, workspace_id: Optional[str] = None, memory_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Deterministic provider-free DB search used by the public baseline and smokes.

        Workspace isolation rule: when workspace_id is provided, every content/chunk
        candidate must match that workspace. This intentionally avoids provider calls.
        """
        terms = self._query_terms(query)
        if not terms:
            return []
        like_patterns = [f"%{term}%" for term in terms]
        where_parts = ["c.workspace_id = %s::uuid"] if workspace_id else []
        params: List[Any] = [workspace_id] if workspace_id else []
        text_match = " OR ".join(["LOWER(ch.chunk_text) LIKE %s" for _ in like_patterns])
        where_parts.append(f"({text_match})")
        params.extend(like_patterns)
        if memory_types:
            where_parts.append("c.memory_type = ANY(%s::text[])")
            params.append(list(memory_types))
        where = " AND ".join(where_parts)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        c.content_id::text AS content_id,
                        ch.chunk_id::text AS chunk_id,
                        c.workspace_id::text AS workspace_id,
                        ch.chunk_text AS text,
                        ch.chunk_index
                    FROM content_chunks ch
                    JOIN content_items c ON c.content_id = ch.content_id
                    WHERE {where}
                    ORDER BY ch.created_at DESC, ch.chunk_index ASC
                    LIMIT 25
                    """,
                    tuple(params),
                )
                rows = [dict(r) for r in cur.fetchall()]
        results: List[Dict[str, Any]] = []
        for row in rows:
            text = (row.get("text") or "").lower()
            match_count = sum(1 for term in terms if term in text)
            score = 0.5 + min(match_count, 5) * 0.1
            results.append(
                {
                    "id": row["content_id"],
                    "content_id": row["content_id"],
                    "chunk_id": row["chunk_id"],
                    "workspace_id": row["workspace_id"],
                    "score": score,
                    "text": row["text"],
                    "retrieval_path": "content_chunk_workspace_scoped",
                }
            )
        return results

    def _hub_linked_results(self, query: str, workspace_id: Optional[str] = None, memory_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not workspace_id:
            return []
        hub = self.hub_store.match_query(query, workspace_id=workspace_id)
        if not hub:
            return []
        content_ids = self.hub_store.get_hub_content_ids(hub["hub_id"], workspace_id=workspace_id)
        if not content_ids:
            return []
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                hub_params: List[Any] = [workspace_id, content_ids]
                hub_where = "c.workspace_id = %s::uuid AND c.content_id = ANY(%s::uuid[])"
                if memory_types:
                    hub_where += " AND c.memory_type = ANY(%s::text[])"
                    hub_params.append(list(memory_types))
                cur.execute(
                    f"""
                    SELECT
                        c.content_id::text AS content_id,
                        ch.chunk_id::text AS chunk_id,
                        c.workspace_id::text AS workspace_id,
                        ch.chunk_text AS text,
                        ch.chunk_index
                    FROM content_items c
                    LEFT JOIN content_chunks ch ON ch.content_id = c.content_id AND ch.workspace_id = c.workspace_id
                    WHERE {hub_where}
                    ORDER BY ch.created_at DESC NULLS LAST, ch.chunk_index ASC NULLS LAST
                    LIMIT 25
                    """,
                    tuple(hub_params),
                )
                rows = [dict(r) for r in cur.fetchall()]
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "id": row["content_id"],
                    "content_id": row["content_id"],
                    "chunk_id": row.get("chunk_id"),
                    "workspace_id": row["workspace_id"],
                    "score": 0.95,
                    "text": row.get("text") or "",
                    "hub_match": hub["hub_id"],
                    "retrieval_path": "hub_link_workspace_scoped",
                }
            )
        return results

    def _deterministic_rerank(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(results, key=lambda x: x.get("score", 0), reverse=True)

    def search(
        self,
        query: str,
        max_hops: int = 1,
        min_confidence: float = 0.7,
        graph_boost: float = 0.1,
        workspace_id: Optional[str] = None,
        memory_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        vector_search = lambda q: self._deterministic_vector_search(q, workspace_id=workspace_id, memory_types=memory_types)
        results = self.adapter.search(
            query=query,
            max_hops=max_hops,
            min_confidence=min_confidence,
            graph_boost=graph_boost,
            workspace_id=workspace_id,
            vector_search_fn=vector_search,
        )
        seen = {str(r.get("content_id") or r.get("id")) for r in results}
        for row in self._hub_linked_results(query, workspace_id=workspace_id, memory_types=memory_types):
            rid = str(row.get("content_id") or row.get("id"))
            if rid not in seen:
                seen.add(rid)
                results.append(row)
        return self._deterministic_rerank(results)
