"""Read-only service for B11 computed conflict candidates.

B11 invariant: computed conflict candidates only. This module must not arbitrate
truth, mutate stored content, or call providers.
"""
from __future__ import annotations

from typing import Any, List, Optional

from psycopg2.extras import RealDictCursor

from memory_lab.conflicts.detector import ConflictSourceRow, detect_conflict_candidates
from memory_lab.conflicts.markers import normalize_scope
from memory_lab.conflicts.models import ConflictSearchResponse


def _memory_types(memory_type: Optional[str], memory_types: Optional[List[str]]) -> Optional[List[str]]:
    values: List[str] = []
    if memory_type:
        values.append(memory_type)
    if memory_types:
        values.extend(memory_types)
    deduped = sorted({v for v in values if v})
    return deduped or None


def _fetch_rows(conn: Any, *, workspace_id: str, query: Optional[str], scope: Optional[str], memory_type: Optional[str], memory_types: Optional[List[str]], source_limit: int) -> List[ConflictSourceRow]:
    params: List[Any] = [workspace_id]
    where = ["ci.workspace_id = %s::uuid"]
    mts = _memory_types(memory_type, memory_types)
    if mts:
        where.append("ci.memory_type = ANY(%s::text[])")
        params.append(mts)
    if scope:
        where.append("(ci.current_state_scope IS NULL OR ci.current_state_scope = %s)")
        params.append(normalize_scope(scope))
    if query:
        where.append("(LOWER(COALESCE(ch.chunk_text, '')) LIKE %s OR LOWER(COALESCE(ci.current_state_scope, '')) LIKE %s)")
        q = f"%{query.lower()}%"
        params.extend([q, q])
    params.append(source_limit)
    sql = f"""
        SELECT ci.content_id::text AS content_id, ci.workspace_id::text AS workspace_id,
               ci.memory_type, ci.memory_sub_type, ci.classify_confidence,
               ci.is_current, ci.current_state_scope, ci.state_identity,
               ci.cs_supersedes_content_id::text AS cs_supersedes_content_id,
               ch.chunk_id::text AS chunk_id, COALESCE(ch.chunk_text, '') AS text,
               a.state_status, a.supersedes_content_id::text AS anchor_supersedes_content_id
          FROM content_items ci
          LEFT JOIN content_chunks ch ON ch.content_id = ci.content_id AND (ch.workspace_id = ci.workspace_id OR ch.workspace_id IS NULL)
          LEFT JOIN cb_current_state_anchors a ON a.content_id = ci.content_id AND a.workspace_id = ci.workspace_id
         WHERE {' AND '.join(where)}
         ORDER BY ci.created_at DESC, ch.chunk_index ASC NULLS LAST
         LIMIT %s
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, tuple(params))
        return [ConflictSourceRow(**dict(r)) for r in cur.fetchall()]


def search_conflict_candidates(conn: Any, *, workspace_id: str, query: Optional[str] = None, scope: Optional[str] = None, memory_type: Optional[str] = None, memory_types: Optional[List[str]] = None, include_resolved: bool = True, limit: int = 10, workspace_source: Optional[str] = None) -> ConflictSearchResponse:
    if not workspace_id:
        return ConflictSearchResponse(conflicts=[], count=0, workspace_id="", workspace_source=workspace_source)
    safe_limit = max(0, min(int(limit or 10), 50))
    rows = _fetch_rows(conn, workspace_id=workspace_id, query=query, scope=scope, memory_type=memory_type, memory_types=memory_types, source_limit=max(safe_limit * 10, 50))
    candidates = detect_conflict_candidates(rows, workspace_id=workspace_id, scope=scope, memory_type=memory_type, include_resolved=include_resolved, limit=safe_limit)
    return ConflictSearchResponse(conflicts=candidates, count=len(candidates), workspace_id=workspace_id, workspace_source=workspace_source)
