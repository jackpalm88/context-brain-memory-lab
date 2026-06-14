"""Deterministic B15 graph health scoring service."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .alias_hygiene import AliasHygieneService
from .health_models import (
    AliasCandidate,
    DEFAULT_NON_CLAIMS,
    GraphHealthComponentScores,
    GraphHealthReport,
    GraphHealthWarning,
    HubRecallMetrics,
    IndexSearchabilityMetrics,
    IndexingStatus,
    TopologyMetrics,
)
from .hub_recall_health import HubRecallHealthService


WARNING_MISSING_ITEM_EMBEDDING = "MISSING_ITEM_EMBEDDING"
WARNING_NULL_EMBEDDING_BACKLOG = "NULL_EMBEDDING_BACKLOG"
WARNING_STALE_INDEX_NOT_SEARCHABLE = "STALE_INDEX_NOT_SEARCHABLE"
WARNING_GRAPH_VECTOR_INDEX_MISMATCH = "GRAPH_VECTOR_INDEX_MISMATCH"


class GraphHealthService:
    """Pure in-memory graph health evaluator.

    The service accepts already-read records. It performs no database writes,
    provider calls, embedding calls, graph mutations, alias merges, or truth
    arbitration.
    """

    def evaluate(
        self,
        *,
        nodes: Optional[Iterable[str]] = None,
        edges: Optional[Iterable[Any]] = None,
        content_items: Optional[Iterable[Dict[str, Any]]] = None,
        hub_links: Optional[Dict[str, Iterable[str]]] = None,
        retrieval_observations: Optional[Dict[Tuple[str, str], bool]] = None,
        alias_labels: Optional[Iterable[str]] = None,
        now: Optional[datetime] = None,
    ) -> GraphHealthReport:
        now = now or datetime.now(timezone.utc)
        content = [dict(item) for item in (content_items or [])]
        hub_links = {str(k): [str(v) for v in vals] for k, vals in (hub_links or {}).items()}
        graph_edges = list(edges or [])
        graph_nodes = set(str(n) for n in (nodes or []))

        for edge in graph_edges:
            a, b = _edge_nodes(edge)
            graph_nodes.add(a)
            graph_nodes.add(b)
        for item in content:
            cid = str(item.get("content_id"))
            if item.get("graph_reachable"):
                graph_nodes.add(cid)
        for linked in hub_links.values():
            graph_nodes.update(linked)

        topology_metrics = self.compute_topology_metrics(graph_nodes, graph_edges)
        index_metrics, index_warnings = self.compute_index_searchability(content, now)

        hub_report = HubRecallHealthService().evaluate(
            content_items=content,
            hub_links=hub_links,
            retrieval_observations=retrieval_observations or {},
            now=now,
        )
        alias_report = AliasHygieneService().generate_candidates(alias_labels or [])

        component_scores = GraphHealthComponentScores(
            topology_score=self.score_topology(topology_metrics),
            index_searchability_score=self.score_index_searchability(index_metrics),
            hub_recall_score=hub_report.score,
            alias_hygiene_score=self.score_alias_hygiene(alias_report.candidates),
            consistency_score=self.score_consistency(content, hub_links),
        )

        warnings = list(index_warnings) + list(hub_report.warnings) + list(alias_report.warnings)
        warnings.extend(self._consistency_warnings(content, hub_links))
        affected_content_ids = sorted(
            {cid for w in warnings for cid in w.affected_content_ids}
            | {f.content_id for f in hub_report.findings}
        )
        affected_node_ids = sorted({nid for w in warnings for nid in w.affected_node_ids})

        limitations: List[str] = []
        if not graph_nodes and not graph_edges:
            limitations.append("empty_graph_or_no_graph_data")
        if not content:
            limitations.append("no_content_index_state_provided")
        if hub_report.metrics.linked_count and not hub_report.metrics.retrieval_observed_available:
            limitations.append("retrieval_observed_unavailable_or_not_provided")

        status = "ok"
        if warnings or limitations:
            status = "limited" if limitations else "degraded"

        return GraphHealthReport(
            status=status,
            health_score=component_scores.total,
            component_scores=component_scores,
            topology_metrics=topology_metrics,
            index_searchability_metrics=index_metrics,
            hub_recall_metrics=hub_report.metrics,
            warnings=warnings,
            affected_content_ids=affected_content_ids,
            affected_node_ids=affected_node_ids,
            hub_recall_findings=hub_report.findings,
            alias_candidates=alias_report.candidates,
            limitations=limitations + hub_report.limitations + alias_report.limitations,
            non_claims=DEFAULT_NON_CLAIMS,
        )

    def compute_topology_metrics(self, nodes: Iterable[str], edges: Iterable[Any]) -> TopologyMetrics:
        node_set: Set[str] = set(str(n) for n in nodes)
        adjacency: Dict[str, Set[str]] = defaultdict(set)
        edge_count = 0
        for edge in edges:
            a, b = _edge_nodes(edge)
            node_set.update([a, b])
            adjacency[a].add(b)
            adjacency[b].add(a)
            edge_count += 1

        if not node_set:
            return TopologyMetrics()

        degrees = {node: len(adjacency.get(node, set())) for node in node_set}
        isolated = sum(1 for degree in degrees.values() if degree == 0)
        low_degree = sum(1 for degree in degrees.values() if degree <= 1)
        largest = self._largest_component_size(node_set, adjacency)
        coverage = largest / len(node_set) if node_set else 0.0
        return TopologyMetrics(
            node_count=len(node_set),
            edge_count=edge_count,
            isolated_node_count=isolated,
            low_degree_node_count=low_degree,
            largest_component_size=largest,
            largest_component_coverage=round(coverage, 4),
        )

    def score_topology(self, metrics: TopologyMetrics) -> int:
        if metrics.node_count == 0:
            return 0
        largest = round(10 * metrics.largest_component_coverage)
        isolated_ratio = metrics.isolated_node_count / metrics.node_count
        low_ratio = metrics.low_degree_node_count / metrics.node_count
        isolated_score = round(8 * (1 - isolated_ratio))
        low_degree_score = round(7 * (1 - low_ratio))
        return _clamp(largest + isolated_score + low_degree_score, 0, 25)

    def compute_index_searchability(
        self, content_items: Sequence[Dict[str, Any]], now: datetime
    ) -> Tuple[IndexSearchabilityMetrics, List[GraphHealthWarning]]:
        warnings: List[GraphHealthWarning] = []
        searchable = 0
        missing_embedding: List[str] = []
        stale: List[str] = []
        null_backlog: List[str] = []

        for item in content_items:
            cid = str(item.get("content_id"))
            status = derive_indexing_status(item, now)
            item["indexing_status"] = status.value
            item["searchable"] = bool(item.get("searchable", status == IndexingStatus.SEARCHABLE))
            if item["searchable"]:
                searchable += 1
            if item.get("embedding_present") is False:
                missing_embedding.append(cid)
                if not item["searchable"]:
                    null_backlog.append(cid)
            if status == IndexingStatus.STALE:
                stale.append(cid)

        if missing_embedding:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_MISSING_ITEM_EMBEDDING,
                    message="One or more saved content items have no observable embedding.",
                    affected_content_ids=sorted(missing_embedding),
                )
            )
        if null_backlog:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_NULL_EMBEDDING_BACKLOG,
                    message="Saved content is not searchable because embedding/index data is absent.",
                    affected_content_ids=sorted(null_backlog),
                )
            )
        if stale:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_STALE_INDEX_NOT_SEARCHABLE,
                    severity="critical",
                    message="Content is past searchable_after but remains non-searchable.",
                    affected_content_ids=sorted(stale),
                )
            )

        return (
            IndexSearchabilityMetrics(
                total_saved_count=len(content_items),
                searchable_count=searchable,
                missing_embedding_count=len(missing_embedding),
                stale_count=len(stale),
                null_embedding_backlog_count=len(null_backlog),
            ),
            warnings,
        )

    def score_index_searchability(self, metrics: IndexSearchabilityMetrics) -> int:
        if metrics.total_saved_count == 0:
            return 0
        searchable_ratio = metrics.searchable_count / metrics.total_saved_count
        score = round(20 * searchable_ratio)
        if metrics.stale_count == 0:
            score += 5
        if metrics.null_embedding_backlog_count == 0:
            score += 5
        return _clamp(score, 0, 30)

    def score_alias_hygiene(self, candidates: Sequence[AliasCandidate]) -> int:
        if not candidates:
            return 10
        if all(c.requires_human_review and not c.mutation_allowed for c in candidates):
            return 7
        return 3

    def score_consistency(self, content_items: Sequence[Dict[str, Any]], hub_links: Dict[str, Iterable[str]]) -> int:
        known = {str(item.get("content_id")) for item in content_items}
        linked = {str(cid) for values in hub_links.values() for cid in values}
        dangling = linked - known if known else set()
        graph_unsearchable = [
            str(item.get("content_id"))
            for item in content_items
            if item.get("graph_reachable") and not item.get("searchable")
        ]
        score = 0
        if not dangling:
            score += 4
        if not graph_unsearchable:
            score += 3
        if not dangling and not graph_unsearchable:
            score += 3
        return _clamp(score, 0, 10)

    def _consistency_warnings(
        self, content_items: Sequence[Dict[str, Any]], hub_links: Dict[str, Iterable[str]]
    ) -> List[GraphHealthWarning]:
        warnings = []
        graph_unsearchable = sorted(
            str(item.get("content_id"))
            for item in content_items
            if item.get("graph_reachable") and not item.get("searchable")
        )
        if graph_unsearchable:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_GRAPH_VECTOR_INDEX_MISMATCH,
                    message="Graph-reachable content is not currently searchable.",
                    affected_content_ids=graph_unsearchable,
                )
            )
        return warnings

    @staticmethod
    def _largest_component_size(node_set: Set[str], adjacency: Dict[str, Set[str]]) -> int:
        seen: Set[str] = set()
        largest = 0
        for start in sorted(node_set):
            if start in seen:
                continue
            q = deque([start])
            seen.add(start)
            size = 0
            while q:
                node = q.popleft()
                size += 1
                for nxt in sorted(adjacency.get(node, set())):
                    if nxt not in seen:
                        seen.add(nxt)
                        q.append(nxt)
            largest = max(largest, size)
        return largest


def derive_indexing_status(item: Dict[str, Any], now: datetime) -> IndexingStatus:
    raw = item.get("indexing_status")
    if raw:
        try:
            return IndexingStatus(str(raw))
        except ValueError:
            return IndexingStatus.UNKNOWN
    if item.get("searchable") is True:
        return IndexingStatus.SEARCHABLE
    searchable_after = item.get("searchable_after")
    if isinstance(searchable_after, datetime) and searchable_after <= now:
        return IndexingStatus.STALE
    if item.get("embedding_present") is False:
        return IndexingStatus.PENDING
    return IndexingStatus.UNKNOWN


def _edge_nodes(edge: Any) -> Tuple[str, str]:
    if isinstance(edge, dict):
        return str(edge.get("from_node") or edge.get("source") or edge.get("a")), str(
            edge.get("to_node") or edge.get("target") or edge.get("b")
        )
    if isinstance(edge, (tuple, list)) and len(edge) >= 2:
        return str(edge[0]), str(edge[1])
    raise ValueError(f"Unsupported edge shape: {edge!r}")


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))
