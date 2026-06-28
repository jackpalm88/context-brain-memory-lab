import json
import logging
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.graph.hub_store import HubStore
from memory_lab.graph.hub_edge_store import HubEdgeStore
from memory_lab.ingestion.scorer import score_content
from memory_lab.ingestion.classify_pipeline import classify as _classify
from memory_lab.persistence.body_chunks import persist_body_chunks
from memory_lab.api.utils.content_signatures import compute_content_hash
from memory_lab.ingestion.semantic_enrichment import annotate
from memory_lab.governance.tier_router import route as tier_route
from memory_lab.current_state.resolver import resolve_current_state_after_ingest

logger = logging.getLogger(__name__)


INFERRED_EDGE_ORIGINS = {"inferred_approved", "ai_suggested"}


def _edge_is_inferred(origin):
    return (origin or "") in INFERRED_EDGE_ORIGINS


def filter_snapshot_edges(edges, include_inferred: bool = True, include_curated: bool = True):
    """Filter snapshot edges by origin class.

    PUBLIC IMPROVEMENT over production (where include_inferred is a documented no-op):
    inferred = origin in INFERRED_EDGE_ORIGINS (machine-suggested); curated = everything
    else (manual / migration_localStorage / unset). Both flags default True (backward
    compatible); both False yields an empty edge list.
    """
    result = []
    for edge in edges:
        origin = edge.get("origin") if isinstance(edge, dict) else getattr(edge, "origin", None)
        inferred = _edge_is_inferred(origin)
        if (inferred and include_inferred) or ((not inferred) and include_curated):
            result.append(edge)
    return result


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

    def _find_duplicate_content_id(self, content_hash: str, workspace_id: Optional[str]) -> Optional[str]:
        """content_id of an existing persisted row with this hash in the same
        workspace, else None. Workspace scope uses IS NOT DISTINCT FROM so NULL
        (unknown) workspaces dedup within their own bucket."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT content_id::text AS content_id
                      FROM content_items
                     WHERE content_hash = %s
                       AND workspace_id IS NOT DISTINCT FROM %s::uuid
                     LIMIT 1
                    """,
                    (content_hash, workspace_id),
                )
                row = cur.fetchone()
        return row["content_id"] if row else None

    def create_content_minimal(
        self,
        content: Optional[str] = None,
        workspace_id: Optional[str] = None,
        workspace_source: Optional[str] = None,
        created_by_subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        content_hash = compute_content_hash(content)
        existing_id = self._find_duplicate_content_id(content_hash, workspace_id)
        if existing_id is not None:
            duplicate_response: Dict[str, Any] = {
                "content_id": existing_id,
                "created": False,
                "persisted": True,
                "discarded": False,
                "duplicate": True,
                "mode": "deduplicated",
            }
            duplicate_response.update(self._workspace_meta(workspace_id, workspace_source))
            return duplicate_response

        event = score_content(content or "")
        tier_decision = tier_route(
            composite_score=event.scores.composite,
            circuit_open=event.circuit_open,
            quality_score=event.scores.quality,
        )
        tier = tier_decision.tier
        tier_reason = tier_decision.reason

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

        base_response: Dict[str, Any] = {
            "created": False,
            "persisted": False,
            "discarded": not tier_decision.should_persist,
            "mode": "governed_discarded" if not tier_decision.should_persist else ("governed_fallback" if event.fallback_reason else "governed"),
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
        base_response.update(self._workspace_meta(workspace_id, workspace_source))

        if not tier_decision.should_persist:
            return base_response

        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO content_items (workspace_id, created_by_subject, content_hash)
                    VALUES (%s::uuid, %s, %s)
                    RETURNING content_id::text AS content_id
                    """,
                    (workspace_id, created_by_subject, content_hash),
                )
                row = cur.fetchone()
                conn.commit()

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

        # M10.1: persist submitted body as content_chunks (chunk_index 0). Deterministic;
        # embedding is opt-in/provider-gated and off on this path by default.
        with self._conn() as conn:
            with conn.cursor() as cur:
                persist_body_chunks(cur, row["content_id"], workspace_id, content or "")
                conn.commit()

        # T3: classify write — best-effort, isolated; failure never rolls back T1/T2
        classify_meta: Dict[str, Any] = self._run_classify_and_write(
            content=content or "",
            content_id=row["content_id"],
            workspace_id=workspace_id,
            tier=tier,
            composite_score=event.scores.composite,
        ) or {}

        # T4: current-state resolver — best-effort, after classify write, persisted rows only.
        # Resolver owns current-state fields; classify remains limited to classify-owned fields.
        current_state_meta: Dict[str, Any] = {}
        try:
            confidence = classify_meta.get("classify_confidence")
            if confidence is not None and confidence >= 0.70:
                with self._conn() as conn:
                    resolution = resolve_current_state_after_ingest(
                        conn,
                        workspace_id=workspace_id,
                        content_id=row["content_id"],
                        memory_type=classify_meta.get("memory_type"),
                        memory_sub_type=classify_meta.get("memory_sub_type"),
                        classify_confidence=confidence,
                        signals=classify_meta.get("signals"),
                        project_topic=classify_meta.get("project_topic"),
                        domain_hint=classify_meta.get("domain_hint"),
                        content_text=content or "",
                    )
                current_state_meta = resolution.to_dict()
        except Exception as exc:
            logger.warning("[api_adapter] current-state resolve failed for %s: %s", row["content_id"], exc)
            current_state_meta = {"status": "deferred", "reason": "resolver_error"}

        # T5: optional semantic enrichment - best-effort; the provider is an
        # implementation detail and a missing/degraded provider never blocks the save.
        topic_tags: List[str] = []
        meta_tags: List[str] = []
        try:
            annotation = annotate(content or "", domain_hint=classify_meta.get("domain_hint"))
            topic_tags, meta_tags = annotation.topic_tags, annotation.meta_tags
            if topic_tags or meta_tags:
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE content_items SET topic_tags = %s, meta_tags = %s WHERE content_id = %s::uuid",
                            (topic_tags, meta_tags, row["content_id"]),
                        )
                        conn.commit()
        except Exception as exc:
            logger.warning("[api_adapter] semantic enrichment failed for %s: %s", row["content_id"], exc)

        response: Dict[str, Any] = {
            **base_response,
            "content_id": row["content_id"],
            "created": True,
            "persisted": True,
            "discarded": False,
            "duplicate": False,
            "memory_type": classify_meta.get("memory_type"),
            "memory_sub_type": classify_meta.get("memory_sub_type"),
            "classify_confidence": classify_meta.get("classify_confidence"),
            "classify_mode": classify_meta.get("classify_mode", "heuristic_v1"),
            "classify_status": classify_meta.get("classify_status", "deferred"),
            "topic_tags": topic_tags,
            "meta_tags": meta_tags,
        }
        if current_state_meta:
            response.update({
                "current_state_status": current_state_meta.get("status"),
                "current_state_reason": current_state_meta.get("reason"),
                "current_state_scope": current_state_meta.get("current_state_scope"),
                "cs_supersedes_content_id": current_state_meta.get("supersedes_content_id"),
            })
        return response

    # ---------------------------------------------------------------------------
    # T3: classify write helper
    # ---------------------------------------------------------------------------

    def _run_classify_and_write(
        self,
        content: str,
        content_id: str,
        workspace_id: Optional[str],
        tier: str,
        composite_score: float,
    ) -> Optional[Dict[str, Any]]:
        """
        T3: best-effort classify write.  Never raises.  Returns classify summary or None on failure.

        Writes classify-owned fields only:
          content_items.memory_type, memory_sub_type, classify_confidence, classified_at
          cb_classification_history (active row, deactivates prior active)
          content_items.domain_id (only when confidence >= 0.70)

        NEVER writes: is_current, current_state_scope, cs_supersedes_content_id.
        """
        try:
            result = _classify(content=content, tier=tier, composite_score=composite_score)
        except Exception as exc:
            logger.warning("[api_adapter] classify raised unexpectedly for %s: %s", content_id, exc)
            result = None

        if result is None:
            return None

        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    # Dedup: skip write if identical active classification already exists
                    cur.execute(
                        """
                        SELECT 1 FROM cb_classification_history
                         WHERE content_id = %s::uuid
                           AND memory_type = %s
                           AND classifier_version = 'heuristic_v1'
                           AND is_active_classification = TRUE
                         LIMIT 1
                        """,
                        (content_id, result.memory_type),
                    )
                    if cur.fetchone():
                        return {
                            "memory_type": result.memory_type,
                            "memory_sub_type": result.memory_sub_type,
                            "classify_confidence": result.confidence,
                            "classify_mode": "heuristic_v1",
                            "classify_status": "classified",
                            "signals": result.signals,
                            "project_topic": result.project_topic,
                            "domain_hint": result.domain_hint,
                            "dedup": True,
                        }

                    # T3a: update classify-owned columns on content_items
                    cur.execute(
                        """
                        UPDATE content_items
                           SET memory_type         = %s,
                               memory_sub_type     = %s,
                               classify_confidence = %s,
                               classified_at       = NOW()
                         WHERE content_id = %s::uuid
                        """,
                        (result.memory_type, result.memory_sub_type, result.confidence, content_id),
                    )

                    # T3b: deactivate prior active classification history rows
                    cur.execute(
                        """
                        UPDATE cb_classification_history
                           SET is_active_classification = FALSE
                         WHERE content_id = %s::uuid
                           AND is_active_classification = TRUE
                        """,
                        (content_id,),
                    )

                    # T3b: insert new active classification row (only if workspace_id known)
                    if workspace_id:
                        cur.execute(
                            """
                            INSERT INTO cb_classification_history
                                (workspace_id, content_id, memory_type, memory_sub_type,
                                 classify_confidence, classifier_version, project_topic,
                                 classification_signals, is_active_classification)
                            VALUES
                                (%s::uuid, %s::uuid, %s, %s, %s,
                                 'heuristic_v1', %s, %s::jsonb, TRUE)
                            """,
                            (
                                workspace_id,
                                content_id,
                                result.memory_type,
                                result.memory_sub_type,
                                result.confidence,
                                result.project_topic,
                                json.dumps(result.signals),
                            ),
                        )

                    # T3c: domain upsert + link — only when confident enough
                    if result.domain_hint and result.confidence >= 0.70 and workspace_id:
                        cur.execute(
                            """
                            INSERT INTO cb_discovered_domains (workspace_id, domain_name, source)
                            VALUES (%s::uuid, %s, 'auto_classify')
                            ON CONFLICT (workspace_id, domain_name) DO NOTHING
                            """,
                            (workspace_id, result.domain_hint),
                        )
                        cur.execute(
                            """
                            UPDATE content_items
                               SET domain_id = (
                                   SELECT domain_id FROM cb_discovered_domains
                                    WHERE workspace_id = %s::uuid
                                      AND domain_name = %s
                                    LIMIT 1
                               )
                             WHERE content_id = %s::uuid
                            """,
                            (workspace_id, result.domain_hint, content_id),
                        )

                    conn.commit()

            return {
                "memory_type": result.memory_type,
                "memory_sub_type": result.memory_sub_type,
                "classify_confidence": result.confidence,
                "classify_mode": "heuristic_v1",
                "classify_status": "classified",
                "signals": result.signals,
                "project_topic": result.project_topic,
                "domain_hint": result.domain_hint,
            }

        except Exception as exc:
            logger.warning("[api_adapter] classify write failed for %s: %s", content_id, exc)
            return None

    def set_quick_summary(self, content_id: str, quick_summary: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["content_id = %s::uuid"]
        params: List[Any] = [quick_summary, content_id]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE content_items
                       SET quick_summary = %s, updated_at = NOW()
                     WHERE {' AND '.join(conditions)}
                    RETURNING content_id::text AS content_id,
                              workspace_id::text AS workspace_id,
                              quick_summary,
                              updated_at
                    """,
                    tuple(params),
                )
                row = cur.fetchone()

        if not row:
            return None
        return {
            "content_id": row["content_id"],
            "workspace_id": row.get("workspace_id"),
            "quick_summary": row.get("quick_summary"),
            "updated": True,
            "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
        }

    def get_content_metadata(self, content_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["ci.content_id = %s::uuid"]
        params: List[Any] = [content_id]
        if workspace_id:
            conditions.append("ci.workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT ci.content_id::text AS content_id,
                           ci.node_type,
                           ci.quick_summary,
                           ci.memory_type,
                           dd.domain_name AS domain,
                           COALESCE(sum(ch.word_count), 0)::int AS word_count,
                           ci.created_by_subject,
                           ci.created_at,
                           ci.updated_at
                      FROM content_items ci
                      LEFT JOIN cb_discovered_domains dd ON dd.domain_id = ci.domain_id
                      LEFT JOIN content_chunks ch ON ch.content_id = ci.content_id
                     WHERE {' AND '.join(conditions)}
                     GROUP BY ci.content_id, ci.node_type, ci.quick_summary, ci.memory_type, dd.domain_name, ci.created_by_subject, ci.created_at, ci.updated_at
                    """,
                    tuple(params),
                )
                row = cur.fetchone()

        if not row:
            return None
        return {
            "content_id": row["content_id"],
            "node_type": row.get("node_type"),
            "quick_summary": row.get("quick_summary"),
            "memory_type": row.get("memory_type"),
            "domain": row.get("domain"),
            "word_count": row.get("word_count") or 0,
            "created_by_subject": row.get("created_by_subject"),
            "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
            "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
        }

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
                           created_by_subject,
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
            "created_by_subject": row.get("created_by_subject"),
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

    def create_hub(self, payload: Dict[str, Any], workspace_id: Optional[str] = None, workspace_source: Optional[str] = None, created_by_subject: Optional[str] = None) -> Dict[str, Any]:
        hub = self.hub_store.create_hub(
            title=payload["title"],
            type=payload.get("hub_type", "topic"),
            description=payload.get("description"),
            aliases=payload.get("aliases") or [],
            related_terms=payload.get("related_terms") or [],
            workspace_uuid=workspace_id,
            created_by_subject=created_by_subject,
        )
        hub.update(self._workspace_meta(workspace_id, workspace_source))
        return hub

    def get_hub(self, hub_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_store.get_hub(hub_id, workspace_id=workspace_id)

    def link_content(self, hub_id: str, content_id: str, workspace_id: Optional[str] = None, created_by_subject: Optional[str] = None) -> Dict[str, Any]:
        self.hub_store.link_content(hub_id, content_id, workspace_id=workspace_id, created_by_subject=created_by_subject)
        result = {"hub_id": hub_id, "content_id": content_id, "linked": True}
        if workspace_id:
            result["workspace_id"] = workspace_id
        return result

    def create_edge(self, payload: Dict[str, Any], workspace_id: Optional[str] = None, created_by: Optional[str] = None) -> Dict[str, Any]:
        return self.hub_edge_store.create_edge(
            source_hub_id=payload["source_hub_id"],
            target_hub_id=payload["target_hub_id"],
            edge_type=payload["edge_type"],
            status=payload.get("status", "manual"),
            origin=payload.get("origin", "manual"),
            confidence=payload.get("confidence"),
            reason=payload.get("reason"),
            note=payload.get("note"),
            created_by=created_by,
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

    def update_edge(self, edge_id: str, updates: Dict[str, Any], workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_edge_store.update_edge(edge_id, updates, workspace_id=workspace_id)

    def approve_inferred_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        note: Optional[str] = None,
        workspace_id: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.hub_edge_store.approve_inferred_edge(
            source_hub_id=source_hub_id,
            target_hub_id=target_hub_id,
            edge_type=edge_type,
            reason=reason,
            confidence=confidence,
            note=note,
            created_by=created_by,
            workspace_id=workspace_id,
        )

    def reject_inferred_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        workspace_id: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.hub_edge_store.reject_inferred_edge(
            source_hub_id=source_hub_id,
            target_hub_id=target_hub_id,
            edge_type=edge_type,
            reason=reason,
            note=note,
            created_by=created_by,
            workspace_id=workspace_id,
        )

    def save_and_link_to_hub(
        self,
        content: str,
        hub_id: str,
        workspace_id: Optional[str] = None,
        workspace_source: Optional[str] = None,
        quick_summary: Optional[str] = None,
        save_purpose: Optional[str] = None,
        content_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        created = self.create_content_minimal(content=content, workspace_id=workspace_id, workspace_source=workspace_source)
        unsupported_fields = {
            name: "accepted for production MCP signature parity but not persisted by the public minimal content API"
            for name, value in {"save_purpose": save_purpose, "content_url": content_url}.items()
            if value is not None
        }
        if unsupported_fields:
            created["unsupported_fields"] = unsupported_fields
        if not created.get("persisted") or not created.get("content_id"):
            return {**created, "linked": False, "hub_id": hub_id}
        content_id = created["content_id"]
        if quick_summary is not None:
            created["quick_summary_result"] = self.set_quick_summary(
                content_id=content_id, quick_summary=quick_summary, workspace_id=workspace_id
            )
        linked = self.link_content(hub_id, content_id, workspace_id=workspace_id)
        return {**created, "linked": True, "hub_link": linked, "hub_id": hub_id}

    def set_node_type(self, content_id: str, node_type: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["content_id = %s::uuid"]
        params: List[Any] = [node_type, content_id]
        if workspace_id:
            conditions.append("workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    UPDATE content_items
                       SET node_type = %s, updated_at = NOW()
                     WHERE {' AND '.join(conditions)}
                    RETURNING content_id::text AS content_id,
                              workspace_id::text AS workspace_id,
                              node_type,
                              updated_at
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
        if not row:
            return None
        result = dict(row)
        if result.get("updated_at") is not None:
            result["updated_at"] = result["updated_at"].isoformat()
        return result

    def get_graph_snapshot(self, include_inferred: bool = True, include_curated: bool = True, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        from dataclasses import asdict
        from memory_lab.graph.repository_reader import RepositoryGraphHealthReader

        reader = RepositoryGraphHealthReader(conn_factory=self._conn, workspace_id=workspace_id)
        snapshot = reader.read_snapshot()
        nodes = [asdict(hub) for hub in snapshot.hubs]
        all_edges = [asdict(edge) for edge in snapshot.hub_edges]
        edges = filter_snapshot_edges(all_edges, include_inferred=include_inferred, include_curated=include_curated)
        inferred_count = sum(1 for e in edges if _edge_is_inferred(e.get("origin")))
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "curated_edge_count": len(edges) - inferred_count,
                "inferred_edge_count": inferred_count,
                "content_count": len(snapshot.content_records),
                "hub_content_link_count": len(snapshot.hub_content_links),
            },
            "filters": {"include_inferred": include_inferred, "include_curated": include_curated},
            "schema_version": "public-m7-v1",
            "workspace_id": workspace_id,
            "limitations": list(snapshot.limitations),
            "warnings": list(snapshot.warnings),
        }

    def load_graph_node_full(self, content_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conditions = ["ci.content_id = %s::uuid"]
        params: List[Any] = [content_id]
        if workspace_id:
            conditions.append("ci.workspace_id = %s::uuid")
            params.append(workspace_id)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT ci.content_id::text AS content_id,
                           ci.workspace_id::text AS workspace_id,
                           ci.node_type,
                           ci.quick_summary,
                           ci.memory_type,
                           ci.created_at,
                           ci.updated_at,
                           ci.created_by_subject,
                           COALESCE(string_agg(ch.chunk_text, E'\\n\\n' ORDER BY ch.chunk_index), '') AS full_text,
                           COALESCE(sum(ch.word_count), 0)::int AS word_count
                      FROM content_items ci
                      LEFT JOIN content_chunks ch ON ch.content_id = ci.content_id
                     WHERE {' AND '.join(conditions)}
                     GROUP BY ci.content_id, ci.workspace_id, ci.node_type, ci.quick_summary, ci.memory_type, ci.created_at, ci.updated_at, ci.created_by_subject
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "content_id": row["content_id"],
            "workspace_id": row.get("workspace_id"),
            "node_type": row.get("node_type"),
            "quick_summary": row.get("quick_summary"),
            "memory_type": row.get("memory_type"),
            "full_text": row.get("full_text") or "",
            "word_count": row.get("word_count") or 0,
            "created_by_subject": row.get("created_by_subject"),
            "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
            "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
        }

    def search_graph_preview(self, query: str, node_type: Optional[str] = None, hub_id: Optional[str] = None, limit: int = 10, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        q = f"%{(query or '').lower()}%"
        conditions = ["(LOWER(COALESCE(ci.quick_summary, '')) LIKE %s OR LOWER(COALESCE(ch.chunk_text, '')) LIKE %s)"]
        params: List[Any] = [q, q]
        joins = "LEFT JOIN content_chunks ch ON ch.content_id = ci.content_id"
        select_hub_match = "FALSE AS hub_match"
        score_expr = "max(CASE WHEN LOWER(COALESCE(ci.quick_summary, '')) LIKE %s THEN 2 ELSE 1 END) AS score"
        lead_params: List[Any] = [q]
        if hub_id:
            joins += " LEFT JOIN cb_hub_content hc ON hc.content_id = ci.content_id AND hc.hub_id = %s::uuid"
            params.insert(0, hub_id)
            select_hub_match = "bool_or(hc.hub_id IS NOT NULL) AS hub_match"
        if node_type:
            conditions.append("ci.node_type = %s")
            params.append(node_type)
        if workspace_id:
            conditions.append("ci.workspace_id = %s::uuid")
            params.append(workspace_id)
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT ci.content_id::text AS content_id,
                           ci.node_type,
                           ci.quick_summary,
                           {select_hub_match},
                           CASE WHEN ci.quick_summary IS NULL OR ci.quick_summary = '' THEN TRUE ELSE FALSE END AS load_full_content_recommended,
                           {score_expr}
                      FROM content_items ci
                      {joins}
                     WHERE {' AND '.join(conditions)}
                     GROUP BY ci.content_id, ci.node_type, ci.quick_summary
                     ORDER BY score DESC, ci.content_id
                     LIMIT %s
                    """,
                    tuple(lead_params + params),
                )
                rows = cur.fetchall()
        return {"results": [dict(r) for r in rows], "count": len(rows), "workspace_id": workspace_id}
