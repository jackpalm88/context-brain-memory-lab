"""B16 read-only repository snapshot adapter for graph health inputs.

This module is intentionally not wired into API routes or report generation in
GO_B16_REPOSITORY_READER_ONLY. It provides a deterministic, mutation-free reader
that normalizes repository/database-like rows into snapshots that later gates can
feed into the existing B15 graph health service layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

MUTATION_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REINDEX|VACUUM|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
ALLOWED_SQL_START_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE | re.DOTALL)

BASE_TABLES: Tuple[str, ...] = (
    "content_items",
    "content_chunks",
    "cb_hubs",
    "cb_hub_content",
    "cb_edges",
    "cb_hub_edges",
    "cb_aliases",
    "cb_alias_candidates",
    "cb_query_log",
)


@dataclass(frozen=True)
class RepositoryCapabilities:
    """Detected table/column availability for repository-backed reads."""

    tables: Dict[str, bool] = field(default_factory=dict)
    columns: Dict[str, List[str]] = field(default_factory=dict)

    def has_table(self, table: str) -> bool:
        return bool(self.tables.get(table, False))

    def has_column(self, table: str, column: str) -> bool:
        return column in self.columns.get(table, [])


@dataclass(frozen=True)
class ContentRecord:
    content_id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    node_type: Optional[str] = None
    quick_summary: Optional[str] = None
    quality_score: Optional[float] = None
    composite_score: Optional[float] = None
    tier: Optional[str] = None
    retrieval_count: Optional[int] = None
    last_retrieved_at: Optional[datetime] = None
    memory_type: Optional[str] = None
    is_current: Optional[bool] = None
    current_state_scope: Optional[str] = None
    item_embedding_state: str = "unknown"


@dataclass(frozen=True)
class ChunkEmbeddingState:
    chunk_id: str
    content_id: str
    workspace_id: Optional[str] = None
    chunk_index: Optional[int] = None
    word_count: Optional[int] = None
    has_text: bool = False
    has_embedding: bool = False
    created_at: Optional[datetime] = None
    derived_indexing_status: str = "unknown"


@dataclass(frozen=True)
class HubRecord:
    hub_id: str
    workspace_uuid: Optional[str] = None
    legacy_workspace_id: Optional[str] = None
    title: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    aliases: Tuple[str, ...] = ()
    related_terms: Tuple[str, ...] = ()
    status: Optional[str] = None
    owner_defined: Optional[bool] = None


@dataclass(frozen=True)
class HubContentLink:
    hub_id: str
    content_id: str
    workspace_id: Optional[str] = None
    linked_at: Optional[datetime] = None


@dataclass(frozen=True)
class GraphEdgeRecord:
    from_node: str
    relation: str
    to_node: str
    source_id: Optional[str] = None
    confidence: Optional[float] = None
    workspace_id: Optional[str] = None
    scope: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class HubEdgeRecord:
    id: str
    source_hub_id: str
    target_hub_id: str
    type: str
    status: Optional[str] = None
    origin: Optional[str] = None
    confidence: Optional[float] = None
    weight: Optional[float] = None
    workspace_id: Optional[str] = None
    archived_at: Optional[datetime] = None


@dataclass(frozen=True)
class AliasRecord:
    term: str
    canonical: str
    confidence: Optional[float] = None
    status: Optional[str] = None
    source: Optional[str] = None
    workspace_id: Optional[str] = None
    scope: Optional[str] = None


@dataclass(frozen=True)
class AliasCandidateRecord:
    term_a: str
    term_b: str
    score: float
    source: Optional[str] = None
    status: Optional[str] = "pending"
    workspace_id: Optional[str] = None
    scope: Optional[str] = None
    requires_human_review: bool = True


@dataclass(frozen=True)
class RetrievalObservation:
    content_id: str
    hub_id: Optional[str] = None
    observed: Optional[bool] = None
    observed_at: Optional[datetime] = None
    strength: str = "unknown"
    limitation: Optional[str] = None


@dataclass(frozen=True)
class RepositoryGraphSnapshot:
    data_source: str
    mode: str
    workspace_id: Optional[str] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    capabilities: RepositoryCapabilities = field(default_factory=RepositoryCapabilities)
    content_records: Tuple[ContentRecord, ...] = ()
    chunk_embedding_states: Tuple[ChunkEmbeddingState, ...] = ()
    hubs: Tuple[HubRecord, ...] = ()
    hub_content_links: Tuple[HubContentLink, ...] = ()
    graph_edges: Tuple[GraphEdgeRecord, ...] = ()
    hub_edges: Tuple[HubEdgeRecord, ...] = ()
    alias_records: Tuple[AliasRecord, ...] = ()
    alias_candidates: Tuple[AliasCandidateRecord, ...] = ()
    retrieval_observations: Tuple[RetrievalObservation, ...] = ()
    limitations: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    unknown_fields: Tuple[str, ...] = ()


class ReadOnlySqlViolation(ValueError):
    """Raised when SQL is not a deterministic read-only SELECT/WITH statement."""


class RepositoryGraphHealthReader:
    """Read-only B16 repository adapter.

    Tests can inject ``row_sets`` so no live DB/private CB access is required.
    A later integration gate may pass ``conn_factory`` for real repository reads.
    """

    def __init__(
        self,
        conn_factory: Optional[Callable[[], Any]] = None,
        workspace_id: Optional[str] = None,
        strict_read_only: bool = True,
        now_fn: Optional[Callable[[], datetime]] = None,
        row_sets: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    ) -> None:
        self.conn_factory = conn_factory
        self.workspace_id = str(workspace_id) if workspace_id is not None else None
        self.strict_read_only = strict_read_only
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._row_sets = {str(k): [dict(v) for v in vals] for k, vals in (row_sets or {}).items()}

    def detect_capabilities(self) -> RepositoryCapabilities:
        if self._row_sets:
            columns = {table: sorted({key for row in rows for key in row}) for table, rows in self._row_sets.items()}
            tables = {table: table in self._row_sets for table in BASE_TABLES}
            return RepositoryCapabilities(tables=tables, columns=columns)
        if self.conn_factory is None:
            return RepositoryCapabilities(
                tables={table: False for table in BASE_TABLES},
                columns={},
            )
        sql = """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_name = ANY(%s)
        """
        rows = self._execute_read(sql, (list(BASE_TABLES),))
        columns: Dict[str, List[str]] = {table: [] for table in BASE_TABLES}
        for row in rows:
            table = str(_get(row, "table_name", ""))
            column = str(_get(row, "column_name", ""))
            if table in columns and column:
                columns[table].append(column)
        return RepositoryCapabilities(
            tables={table: bool(columns.get(table)) for table in BASE_TABLES},
            columns={table: sorted(set(cols)) for table, cols in columns.items()},
        )

    def read_snapshot(
        self,
        *,
        hub_id: Optional[str] = None,
        include_alias_candidates: bool = True,
    ) -> RepositoryGraphSnapshot:
        capabilities = self.detect_capabilities()
        limitations: List[str] = []
        warnings: List[str] = []
        unknown_fields = [
            "content_items.item_embedding_state",
            "hub_recall.retrieval_observed_without_explicit_result_content_ids",
        ]
        if not capabilities.has_table("content_items"):
            limitations.append("content_items_table_unavailable")
        if not capabilities.has_table("content_chunks"):
            limitations.append("content_chunks_table_unavailable")
        if not capabilities.has_table("cb_edges"):
            limitations.append("graph_edges_table_unavailable")
        if not capabilities.has_table("cb_aliases"):
            limitations.append("alias_records_table_unavailable")
        if not capabilities.has_table("cb_alias_candidates"):
            limitations.append("alias_candidates_table_unavailable")
        if not capabilities.has_table("cb_query_log"):
            limitations.append("retrieval_result_content_id_log_unavailable")
        else:
            limitations.append("cb_query_log_has_no_verified_result_content_id_mapping")

        content_records = tuple(self._content_records(self._rows("content_items")))
        chunks = tuple(self._chunk_states(self._rows("content_chunks")))
        hubs = tuple(self._hub_records(self._rows("cb_hubs")))
        hub_links = tuple(self._hub_links(self._rows("cb_hub_content"), hub_id=hub_id))
        graph_edges = tuple(self._graph_edges(self._rows("cb_edges")))
        hub_edges = tuple(self._hub_edges(self._rows("cb_hub_edges")))
        alias_records = tuple(self._alias_records(self._rows("cb_aliases")))
        alias_candidates = (
            tuple(self._alias_candidates(self._rows("cb_alias_candidates")))
            if include_alias_candidates
            else ()
        )
        retrieval_observations = tuple(self._retrieval_observations(content_records))

        content_ids_with_chunks = {chunk.content_id for chunk in chunks}
        for content in content_records:
            if content.content_id not in content_ids_with_chunks:
                warnings.append("content_has_no_chunk_index_state")
                break
        if any(chunk.has_text and not chunk.has_embedding for chunk in chunks):
            warnings.append("chunk_embedding_missing_or_null")

        return RepositoryGraphSnapshot(
            data_source="repository",
            mode="repository",
            workspace_id=self.workspace_id,
            generated_at=self.now_fn(),
            capabilities=capabilities,
            content_records=content_records,
            chunk_embedding_states=chunks,
            hubs=hubs,
            hub_content_links=hub_links,
            graph_edges=graph_edges,
            hub_edges=hub_edges,
            alias_records=alias_records,
            alias_candidates=alias_candidates,
            retrieval_observations=retrieval_observations,
            limitations=tuple(sorted(set(limitations))),
            warnings=tuple(sorted(set(warnings))),
            unknown_fields=tuple(sorted(set(unknown_fields))),
        )

    def read_graph_health_inputs(self) -> Dict[str, Any]:
        snapshot = self.read_snapshot()
        return self._graph_health_inputs_from_snapshot(snapshot)

    def read_hub_recall_inputs(self, hub_id: str) -> Dict[str, Any]:
        snapshot = self.read_snapshot(hub_id=hub_id)
        inputs = self._graph_health_inputs_from_snapshot(snapshot)
        return {
            "content_items": inputs["content_items"],
            "hub_links": {str(hub_id): inputs["hub_links"].get(str(hub_id), [])},
            "retrieval_observations": inputs["retrieval_observations"],
            "hub_id": str(hub_id),
            "limitations": snapshot.limitations,
            "unknown_fields": snapshot.unknown_fields,
        }

    def read_alias_candidate_inputs(self) -> Dict[str, Any]:
        snapshot = self.read_snapshot(include_alias_candidates=True)
        labels = sorted(
            {
                value
                for hub in snapshot.hubs
                for value in (hub.title, *hub.aliases, *hub.related_terms)
                if value
            }
            | {candidate.term_a for candidate in snapshot.alias_candidates}
            | {candidate.term_b for candidate in snapshot.alias_candidates}
            | {alias.term for alias in snapshot.alias_records}
            | {alias.canonical for alias in snapshot.alias_records}
        )
        return {
            "alias_labels": labels,
            "alias_candidates": snapshot.alias_candidates,
            "limitations": snapshot.limitations,
            "unknown_fields": snapshot.unknown_fields,
        }

    def unavailable_snapshot(self, reason: str) -> RepositoryGraphSnapshot:
        return RepositoryGraphSnapshot(
            data_source="unavailable",
            mode="unavailable",
            workspace_id=self.workspace_id,
            generated_at=self.now_fn(),
            limitations=(str(reason), "repository_reader_unavailable"),
            warnings=(),
            unknown_fields=(
                "repository_capabilities",
                "content_items",
                "chunk_embedding_states",
                "hub_recall.retrieval_observed_without_explicit_result_content_ids",
            ),
        )

    def _ensure_read_only_sql(self, sql: str) -> None:
        statement = _strip_sql_comments(sql).strip()
        if self.strict_read_only and MUTATION_SQL_RE.search(statement):
            raise ReadOnlySqlViolation("RepositoryGraphHealthReader only permits read-only SELECT/WITH SQL")
        if self.strict_read_only and not ALLOWED_SQL_START_RE.match(statement):
            raise ReadOnlySqlViolation("RepositoryGraphHealthReader SQL must start with SELECT or WITH")

    def _execute_read(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Mapping[str, Any]]:
        self._ensure_read_only_sql(sql)
        if self.conn_factory is None:
            return []
        conn = self.conn_factory()
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            return [_row_to_dict(row, cur) for row in rows]

    def _rows(self, table: str) -> List[Dict[str, Any]]:
        if table in self._row_sets:
            return [dict(row) for row in self._row_sets[table]]
        if self.conn_factory is None:
            return []
        sql = f"SELECT * FROM {table}"
        return [dict(row) for row in self._execute_read(sql)]

    def _content_records(self, rows: Iterable[Mapping[str, Any]]) -> List[ContentRecord]:
        records = []
        for row in _sorted_rows(rows, "content_id"):
            records.append(
                ContentRecord(
                    content_id=str(_get(row, "content_id")),
                    workspace_id=_str_or_none(_get(row, "workspace_id")),
                    created_at=_get(row, "created_at"),
                    updated_at=_get(row, "updated_at"),
                    node_type=_str_or_none(_get(row, "node_type")),
                    quick_summary=_str_or_none(_get(row, "quick_summary")),
                    quality_score=_float_or_none(_get(row, "quality_score")),
                    composite_score=_float_or_none(_get(row, "composite_score")),
                    tier=_str_or_none(_get(row, "tier")),
                    retrieval_count=_int_or_none(_get(row, "retrieval_count")),
                    last_retrieved_at=_get(row, "last_retrieved_at"),
                    memory_type=_str_or_none(_get(row, "memory_type")),
                    is_current=_bool_or_none(_get(row, "is_current")),
                    current_state_scope=_str_or_none(_get(row, "current_state_scope")),
                    item_embedding_state="unknown",
                )
            )
        return records

    def _chunk_states(self, rows: Iterable[Mapping[str, Any]]) -> List[ChunkEmbeddingState]:
        states = []
        for row in _sorted_rows(rows, "content_id", "chunk_index", "chunk_id"):
            text = _get(row, "chunk_text")
            has_text = bool(str(text).strip()) if text is not None else bool(_get(row, "has_text", False))
            has_embedding = _get(row, "embedding") is not None or bool(_get(row, "has_embedding", False))
            status = "searchable" if has_text and has_embedding else "blocked_empty" if not has_text else "unknown"
            states.append(
                ChunkEmbeddingState(
                    chunk_id=str(_get(row, "chunk_id", f"{_get(row, 'content_id')}:{_get(row, 'chunk_index', 0)}")),
                    content_id=str(_get(row, "content_id")),
                    workspace_id=_str_or_none(_get(row, "workspace_id")),
                    chunk_index=_int_or_none(_get(row, "chunk_index")),
                    word_count=_int_or_none(_get(row, "word_count")),
                    has_text=has_text,
                    has_embedding=has_embedding,
                    created_at=_get(row, "created_at"),
                    derived_indexing_status=status,
                )
            )
        return states

    def _hub_records(self, rows: Iterable[Mapping[str, Any]]) -> List[HubRecord]:
        records = []
        for row in _sorted_rows(rows, "hub_id"):
            records.append(
                HubRecord(
                    hub_id=str(_get(row, "hub_id")),
                    workspace_uuid=_str_or_none(_get(row, "workspace_uuid")),
                    legacy_workspace_id=_str_or_none(_get(row, "workspace_id")),
                    title=_str_or_none(_get(row, "title")),
                    type=_str_or_none(_get(row, "type")),
                    description=_str_or_none(_get(row, "description")),
                    aliases=tuple(_list_of_str(_get(row, "aliases"))),
                    related_terms=tuple(_list_of_str(_get(row, "related_terms"))),
                    status=_str_or_none(_get(row, "status")),
                    owner_defined=_bool_or_none(_get(row, "owner_defined")),
                )
            )
        return records

    def _hub_links(self, rows: Iterable[Mapping[str, Any]], *, hub_id: Optional[str]) -> List[HubContentLink]:
        links = []
        for row in _sorted_rows(rows, "hub_id", "content_id"):
            row_hub_id = str(_get(row, "hub_id"))
            if hub_id is not None and row_hub_id != str(hub_id):
                continue
            links.append(
                HubContentLink(
                    hub_id=row_hub_id,
                    content_id=str(_get(row, "content_id")),
                    workspace_id=_str_or_none(_get(row, "workspace_id")),
                    linked_at=_get(row, "linked_at"),
                )
            )
        return links

    def _graph_edges(self, rows: Iterable[Mapping[str, Any]]) -> List[GraphEdgeRecord]:
        return [
            GraphEdgeRecord(
                from_node=str(_get(row, "from_node")),
                relation=str(_get(row, "relation")),
                to_node=str(_get(row, "to_node")),
                source_id=_str_or_none(_get(row, "source_id")),
                confidence=_float_or_none(_get(row, "confidence")),
                workspace_id=_str_or_none(_get(row, "workspace_id")),
                scope=_str_or_none(_get(row, "scope")),
                created_at=_get(row, "created_at"),
                updated_at=_get(row, "updated_at"),
            )
            for row in _sorted_rows(rows, "from_node", "to_node", "relation")
        ]

    def _hub_edges(self, rows: Iterable[Mapping[str, Any]]) -> List[HubEdgeRecord]:
        return [
            HubEdgeRecord(
                id=str(_get(row, "id", f"{_get(row, 'source_hub_id')}->{_get(row, 'target_hub_id')}")),
                source_hub_id=str(_get(row, "source_hub_id")),
                target_hub_id=str(_get(row, "target_hub_id")),
                type=str(_get(row, "type")),
                status=_str_or_none(_get(row, "status")),
                origin=_str_or_none(_get(row, "origin")),
                confidence=_float_or_none(_get(row, "confidence")),
                weight=_float_or_none(_get(row, "weight")),
                workspace_id=_str_or_none(_get(row, "workspace_id")),
                archived_at=_get(row, "archived_at"),
            )
            for row in _sorted_rows(rows, "source_hub_id", "target_hub_id", "type")
            if _get(row, "archived_at") is None and str(_get(row, "status", "active")) not in {"rejected", "archived"}
        ]

    def _alias_records(self, rows: Iterable[Mapping[str, Any]]) -> List[AliasRecord]:
        return [
            AliasRecord(
                term=str(_get(row, "term")),
                canonical=str(_get(row, "canonical")),
                confidence=_float_or_none(_get(row, "confidence")),
                status=_str_or_none(_get(row, "status")),
                source=_str_or_none(_get(row, "source")),
                workspace_id=_str_or_none(_get(row, "workspace_id")),
                scope=_str_or_none(_get(row, "scope")),
            )
            for row in _sorted_rows(rows, "term", "canonical")
        ]

    def _alias_candidates(self, rows: Iterable[Mapping[str, Any]]) -> List[AliasCandidateRecord]:
        return [
            AliasCandidateRecord(
                term_a=str(_get(row, "term_a")),
                term_b=str(_get(row, "term_b")),
                score=float(_get(row, "score", 0.0)),
                source=_str_or_none(_get(row, "source")),
                status=_str_or_none(_get(row, "status", "pending")),
                workspace_id=_str_or_none(_get(row, "workspace_id")),
                scope=_str_or_none(_get(row, "scope")),
                requires_human_review=True,
            )
            for row in _sorted_rows(rows, "term_a", "term_b")
            if str(_get(row, "status", "pending")) == "pending"
        ]

    def _retrieval_observations(self, content_records: Sequence[ContentRecord]) -> List[RetrievalObservation]:
        observations: List[RetrievalObservation] = []
        for record in content_records:
            if record.retrieval_count and record.retrieval_count > 0:
                observations.append(
                    RetrievalObservation(
                        content_id=record.content_id,
                        hub_id=None,
                        observed=True,
                        observed_at=record.last_retrieved_at,
                        strength="weak_content_counter",
                        limitation="content-level retrieval counter is not hub-specific",
                    )
                )
        return observations

    def _graph_health_inputs_from_snapshot(self, snapshot: RepositoryGraphSnapshot) -> Dict[str, Any]:
        chunk_by_content: Dict[str, List[ChunkEmbeddingState]] = {}
        for chunk in snapshot.chunk_embedding_states:
            chunk_by_content.setdefault(chunk.content_id, []).append(chunk)
        hub_link_map: Dict[str, List[str]] = {}
        for link in snapshot.hub_content_links:
            hub_link_map.setdefault(link.hub_id, []).append(link.content_id)
        graph_nodes = {edge.from_node for edge in snapshot.graph_edges} | {edge.to_node for edge in snapshot.graph_edges}
        graph_nodes.update(edge.source_hub_id for edge in snapshot.hub_edges)
        graph_nodes.update(edge.target_hub_id for edge in snapshot.hub_edges)
        graph_edges: List[Tuple[str, str]] = [(edge.from_node, edge.to_node) for edge in snapshot.graph_edges]
        graph_edges.extend((edge.source_hub_id, edge.target_hub_id) for edge in snapshot.hub_edges)
        content_items = []
        for record in snapshot.content_records:
            chunks = chunk_by_content.get(record.content_id, [])
            has_any_text = any(chunk.has_text for chunk in chunks)
            has_any_embedding = any(chunk.has_embedding for chunk in chunks)
            searchable = has_any_text and has_any_embedding
            indexing_status = "searchable" if searchable else "blocked_empty" if chunks and not has_any_text else "unknown"
            content_items.append(
                {
                    "content_id": record.content_id,
                    "saved": True,
                    "searchable": searchable,
                    "hub_linked": any(record.content_id in ids for ids in hub_link_map.values()),
                    "graph_reachable": record.content_id in graph_nodes,
                    "retrieval_observed": None,
                    "indexing_status": indexing_status,
                    "embedding_present": has_any_embedding if chunks else None,
                    "item_embedding_state": record.item_embedding_state,
                }
            )
        return {
            "nodes": sorted(graph_nodes),
            "edges": graph_edges,
            "content_items": content_items,
            "hub_links": {hub: sorted(ids) for hub, ids in sorted(hub_link_map.items())},
            "retrieval_observations": {},
            "alias_labels": self.read_alias_candidate_inputs()["alias_labels"] if snapshot.mode == "repository" else [],
            "limitations": snapshot.limitations,
            "unknown_fields": snapshot.unknown_fields,
        }


def _strip_sql_comments(sql: str) -> str:
    without_line_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", without_line_comments, flags=re.DOTALL)


def _row_to_dict(row: Any, cursor: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    description = getattr(cursor, "description", None) or []
    keys = [item[0] for item in description]
    return dict(zip(keys, row))


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    return row[key] if key in row else default


def _sorted_rows(rows: Iterable[Mapping[str, Any]], *keys: str) -> List[Mapping[str, Any]]:
    return sorted((dict(row) for row in rows), key=lambda row: tuple(str(row.get(key, "")) for key in keys))


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _bool_or_none(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def _list_of_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]
