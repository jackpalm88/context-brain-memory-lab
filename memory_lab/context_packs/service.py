from __future__ import annotations

from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.conflicts.service import search_conflict_candidates
from memory_lab.reasoning.answer_synthesizer import normalize_evidence

from .builder import build_context_pack
from .models import ContextPackBuildRequest, ContextPackBuildResponse, ContextPackOmittedItem


def _metadata_by_content_id(conn: Any, *, workspace_id: str, content_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted({c for c in content_ids if c})
    if not ids:
        return {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT ci.content_id::text AS content_id,
                   ci.memory_type, ci.memory_sub_type, ci.classify_confidence,
                   ci.is_current, ci.current_state_scope,
                   ci.cs_supersedes_content_id::text AS cs_supersedes_content_id,
                   a.scope AS anchor_scope, a.state_status, a.supersedes_content_id::text AS anchor_supersedes_content_id,
                   a.canonical_rank, a.state_reason
              FROM content_items ci
              LEFT JOIN cb_current_state_anchors a
                ON a.content_id = ci.content_id AND a.workspace_id = ci.workspace_id
             WHERE ci.workspace_id = %s::uuid
               AND ci.content_id = ANY(%s::uuid[])
             ORDER BY ci.content_id::text ASC
            """,
            (workspace_id, ids),
        )
        return {str(r["content_id"]): dict(r) for r in cur.fetchall()}


def _fetch_current_state_rows(
    conn: Any,
    *,
    workspace_id: str,
    query: Optional[str],
    scope: Optional[str],
    memory_types: Optional[List[str]],
    limit: int,
) -> List[Dict[str, Any]]:
    params: List[Any] = [workspace_id]
    where = ["ci.workspace_id = %s::uuid"]
    if memory_types:
        where.append("ci.memory_type = ANY(%s::text[])")
        params.append(memory_types)
    if scope:
        where.append("ci.current_state_scope = %s")
        params.append(scope)
    elif query:
        where.append("(LOWER(COALESCE(ci.current_state_scope, '')) LIKE %s OR LOWER(COALESCE(ch.chunk_text, '')) LIKE %s)")
        q = f"%{query.lower()}%"
        params.extend([q, q])
    where.append("(ci.is_current IS NOT NULL OR ci.cs_supersedes_content_id IS NOT NULL OR a.state_status IS NOT NULL)")
    params.append(max(limit * 4, limit))
    sql = f"""
        SELECT ci.content_id::text AS content_id,
               ch.chunk_id::text AS chunk_id,
               COALESCE(ch.chunk_text, '') AS snippet,
               ci.memory_type, ci.memory_sub_type, ci.classify_confidence,
               ci.is_current, ci.current_state_scope,
               ci.cs_supersedes_content_id::text AS cs_supersedes_content_id,
               a.scope AS anchor_scope, a.state_status, a.supersedes_content_id::text AS anchor_supersedes_content_id,
               a.canonical_rank, a.state_reason
          FROM content_items ci
          LEFT JOIN content_chunks ch
            ON ch.content_id = ci.content_id
           AND (ch.workspace_id = ci.workspace_id OR ch.workspace_id IS NULL)
           AND ch.chunk_index = 0
          LEFT JOIN cb_current_state_anchors a
            ON a.content_id = ci.content_id AND a.workspace_id = ci.workspace_id
         WHERE {' AND '.join(where)}
         ORDER BY ci.current_state_scope ASC NULLS LAST,
                  ci.memory_type ASC NULLS LAST,
                  a.canonical_rank ASC NULLS LAST,
                  ci.content_id::text ASC
         LIMIT %s
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
    for idx, row in enumerate(rows, start=1):
        row["evidence_id"] = f"cs_{row['content_id']}_{row.get('chunk_id') or idx}"
        row["rank"] = idx
        row["score_kind"] = "current_state_metadata"
        row["source"] = "current_state"
        row["metadata"] = {
            "state_status": row.get("state_status"),
            "anchor_supersedes_content_id": row.get("anchor_supersedes_content_id"),
            "canonical_rank": row.get("canonical_rank"),
            "state_reason": row.get("state_reason"),
        }
    return rows


def _attach_content_metadata(evidence: List[Any], metadata: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for item in evidence:
        row = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        content_id = str(row.get("content_id") or "")
        meta = metadata.get(content_id, {})
        row.update({k: v for k, v in meta.items() if k != "content_id" and v is not None})
        row["metadata"] = {k: v for k, v in meta.items() if k not in {"content_id", "memory_type", "memory_sub_type", "classify_confidence", "is_current", "current_state_scope", "cs_supersedes_content_id"} and v is not None} or row.get("metadata")
        enriched.append(row)
    return enriched


def build_context_pack_for_request(
    *,
    database_url: str,
    request: ContextPackBuildRequest,
    workspace_id: str,
    workspace_source: Optional[str] = None,
) -> ContextPackBuildResponse:
    memory_types = request.resolved_memory_types()
    supporting_evidence: List[Dict[str, Any]] = []
    current_state_rows: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    omitted: List[ContextPackOmittedItem] = []

    with psycopg2.connect(database_url) as conn:
        if request.include_supporting_evidence:
            adapter = RetrievalAdapter(database_url)
            raw_results = adapter.search(
                query=request.effective_query(),
                max_hops=1,
                min_confidence=0.0,
                graph_boost=0.1,
                workspace_id=workspace_id,
                memory_types=memory_types,
            )
            normalized = normalize_evidence(raw_results)[: request.limit]
            metadata = _metadata_by_content_id(conn, workspace_id=workspace_id, content_ids=[e.content_id for e in normalized])
            supporting_evidence = _attach_content_metadata(normalized, metadata)
            if len(raw_results) > request.limit:
                omitted.append(ContextPackOmittedItem(reason="limit_exceeded", source="retrieval", count=len(raw_results) - request.limit))
        else:
            omitted.append(ContextPackOmittedItem(reason="include_flag_disabled", source="retrieval", count=0))

        if request.include_current_state:
            current_state_rows = _fetch_current_state_rows(
                conn,
                workspace_id=workspace_id,
                query=request.query,
                scope=request.scope,
                memory_types=memory_types,
                limit=request.limit,
            )
        else:
            omitted.append(ContextPackOmittedItem(reason="include_flag_disabled", source="current_state", count=0))

        if request.include_conflicts or request.include_counterfindings:
            result = search_conflict_candidates(
                conn,
                workspace_id=workspace_id,
                workspace_source=workspace_source,
                query=request.query,
                scope=request.scope,
                memory_type=request.memory_type,
                memory_types=request.memory_types,
                include_resolved=True,
                limit=request.limit,
            )
            conflicts = [c.model_dump() for c in result.conflicts]
        else:
            omitted.append(ContextPackOmittedItem(reason="include_flag_disabled", source="conflicts", count=0))

    if not request.include_conflicts:
        conflicts = []

    return build_context_pack(
        workspace_id=workspace_id,
        request=request,
        supporting_evidence=supporting_evidence,
        current_state_rows=current_state_rows,
        conflict_candidates=conflicts,
        omitted_items=omitted,
    )
