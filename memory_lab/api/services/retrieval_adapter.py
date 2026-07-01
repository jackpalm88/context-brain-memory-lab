from typing import Any, Dict, List, Callable, Optional
import time

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.graph.adapter import CBGraphAdapter
from memory_lab.graph.hub_store import HubStore
from memory_lab.graph.store import GraphStore
from memory_lab.providers.embedding_backend import EmbeddingBackend, EmbeddingRequest
from memory_lab.retrieval.composite_ranker import rank_by_composite


class RetrievalAdapter:
    """Provider-neutral retrieval adapter with deterministic workspace-scoped DB defaults."""

    def __init__(self, database_url: str, embedding_backend: EmbeddingBackend | None = None, pgvector_retrieval_enabled: bool | None = None):
        self.database_url = database_url
        self.embedding_backend = embedding_backend
        self.pgvector_retrieval_enabled = _pgvector_retrieval_enabled() if pgvector_retrieval_enabled is None else bool(pgvector_retrieval_enabled)
        self.graph_store = GraphStore(database_url)
        self.hub_store = HubStore(database_url)
        self.vector_search_fn: Callable[[str], List[Dict[str, Any]]] = self._deterministic_vector_search
        self.rerank_fn: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]] = self._deterministic_rerank
        self.adapter = CBGraphAdapter(
            graph_store=self.graph_store,
            vector_search_fn=self.vector_search_fn,
            rerank_fn=self.rerank_fn,
        )
        self.last_debug_metadata: Dict[str, Any] = {}

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

    def _embedding_backend(self) -> EmbeddingBackend | None:
        if self.embedding_backend is not None:
            return self.embedding_backend
        if not self.pgvector_retrieval_enabled:
            return None
        from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend

        self.embedding_backend = OpenAIEmbeddingBackend()
        return self.embedding_backend

    def _query_embedding(self, query: str) -> tuple[List[float] | None, str | None]:
        if not self.database_url or not self.pgvector_retrieval_enabled:
            return None, "provider_disabled"
        backend = self._embedding_backend()
        if backend is None or not backend.is_configured:
            return None, "provider_disabled"
        response = backend.embed_text(EmbeddingRequest(text=query))
        if not response.is_ok or response.dimensions != 1536:
            reason = response.failure_reason.value if response.failure_reason is not None else "embedding_degraded"
            return None, reason
        return response.vector, None

    def _pgvector_knn_search(self, query: str, query_vector: List[float], workspace_id: Optional[str] = None, memory_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        where_parts = ["ch.embedding IS NOT NULL"]
        where_params: List[Any] = []
        if workspace_id:
            where_parts.append("c.workspace_id = %s::uuid")
            where_params.append(workspace_id)
        if memory_types:
            where_parts.append("c.memory_type = ANY(%s::text[])")
            where_params.append(list(memory_types))
        query_vector_literal = _vector_literal(query_vector)
        params: List[Any] = [query_vector_literal, *where_params, query_vector_literal]
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
                        ch.chunk_index,
                        (ch.embedding <=> %s::vector) AS distance
                    FROM content_chunks ch
                    JOIN content_items c ON c.content_id = ch.content_id
                    WHERE {where}
                    ORDER BY ch.embedding <=> %s::vector ASC, ch.chunk_index ASC
                    LIMIT 25
                    """,
                    tuple(params),
                )
                rows = [dict(r) for r in cur.fetchall()]
        results: List[Dict[str, Any]] = []
        for row in rows:
            distance = float(row.get("distance") or 0.0)
            results.append(
                {
                    "id": row["content_id"],
                    "content_id": row["content_id"],
                    "chunk_id": row["chunk_id"],
                    "workspace_id": row["workspace_id"],
                    "score": 1.0 / (1.0 + distance),
                    "text": row["text"],
                    "distance": distance,
                    "retrieval_path": "pgvector_knn",
                    "retrieval_mode": "pgvector_knn",
                    "embedding_status": "ok",
                }
            )
        return results

    def search(
        self,
        query: str,
        max_hops: int = 1,
        min_confidence: float = 0.7,
        graph_boost: float = 0.1,
        workspace_id: Optional[str] = None,
        memory_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        started = time.perf_counter()
        query_vector, embedding_degraded = self._query_embedding(query)
        pgvector_attempted = bool(self.pgvector_retrieval_enabled)
        if query_vector is not None:
            vector_search = lambda q: self._pgvector_knn_search(q, query_vector, workspace_id=workspace_id, memory_types=memory_types)
        else:
            vector_search = lambda q: self._deterministic_vector_search(q, workspace_id=workspace_id, memory_types=memory_types)
        results = self.adapter.search(
            query=query,
            max_hops=max_hops,
            min_confidence=min_confidence,
            graph_boost=graph_boost,
            workspace_id=workspace_id,
            vector_search_fn=vector_search,
        )
        fallback_mode = "deterministic_fallback" if query_vector is None else "pgvector_knn"
        for result in results:
            result.setdefault("retrieval_mode", fallback_mode)
            if query_vector is None:
                result.setdefault("retrieval_path", "deterministic_fallback")
                result.setdefault("embedding_status", embedding_degraded or "provider_disabled")
        before_hub_count = len(results)
        seen = {str(r.get("content_id") or r.get("id")) for r in results}
        hub_candidates = self._hub_linked_results(query, workspace_id=workspace_id, memory_types=memory_types)
        hub_added = 0
        for row in hub_candidates:
            rid = str(row.get("content_id") or row.get("id"))
            if rid not in seen:
                seen.add(rid)
                results.append(row)
                hub_added += 1
        # OPENCB-M12-1: the composite Scoring Model v2 final_score is the ranking authority
        # (sort key = (-final_score, distance)), replacing the flat per-path score sort.
        reranked = rank_by_composite(results, query)
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        pgvector_count = sum(1 for row in reranked if row.get("retrieval_mode") == "pgvector_knn" or row.get("retrieval_path") == "pgvector_knn")
        deterministic_count = sum(1 for row in reranked if row.get("retrieval_mode") == "deterministic_fallback" or row.get("retrieval_path") in {"deterministic_fallback", "content_chunk_workspace_scoped"})
        graph_count = sum(1 for row in reranked if row.get("_graph_boosted") or bool(row.get("graph_match")) or len(row.get("source_queries") or []) > 1)
        degraded_reasons = []
        if embedding_degraded:
            degraded_reasons.append(embedding_degraded)
        self.last_debug_metadata = {
            "stage_metrics": {
                "adapter_search": {
                    "attempted": True,
                    "status": "ok",
                    "candidate_count": len(reranked),
                    "output_count": len(reranked),
                    "duration_ms": duration_ms,
                    "reason": None,
                },
                "deterministic_retrieval": {
                    "attempted": query_vector is None,
                    "used": deterministic_count > 0,
                    "skipped": query_vector is not None,
                    "output_count": deterministic_count,
                    "reason": None if deterministic_count else "not_used",
                },
                "pgvector": {
                    "attempted": pgvector_attempted,
                    "used": pgvector_count > 0,
                    "skipped": pgvector_count == 0,
                    "output_count": pgvector_count,
                    "reason": None if pgvector_count else (embedding_degraded or "provider_disabled"),
                },
                "hub_inclusion": {
                    "attempted": bool(workspace_id),
                    "used": hub_added > 0,
                    "skipped": hub_added == 0,
                    "candidate_count": len(hub_candidates),
                    "output_count": hub_added,
                    "reason": None if hub_added else "no_hub_matches",
                },
                "graph_expansion": {
                    "attempted": max_hops > 0,
                    "used": graph_count > 0,
                    "skipped": graph_count == 0,
                    "expanded_query_count": graph_count,
                    "reason": None if graph_count else "no_expanded_terms",
                },
                "dedup_filtering": {
                    "attempted": True,
                    "status": "ok",
                    "input_count": before_hub_count + len(hub_candidates),
                    "output_count": len(reranked),
                    "dropped_count": max((before_hub_count + len(hub_candidates)) - len(reranked), 0),
                    "reason": None,
                },
            },
            "degraded_reasons": degraded_reasons,
        }
        return reranked


def _env_bool(name: str, default: bool = False) -> bool:
    import os

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _pgvector_retrieval_enabled() -> bool:
    return _env_bool("MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED", False)


def _vector_literal(vector: List[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in vector) + "]"
