from dataclasses import replace
from datetime import datetime, timezone

import pytest

from memory_lab.graph.health_service import GraphHealthService
from memory_lab.graph.repository_reader import RepositoryGraphHealthReader

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _rows():
    return {
        "content_items": [
            {"content_id": "c1", "workspace_id": "w1", "retrieval_count": 0},
            {"content_id": "c2", "workspace_id": "w1", "retrieval_count": 0},
        ],
        "content_chunks": [
            {"chunk_id": "ch1", "content_id": "c1", "chunk_index": 0, "chunk_text": "searchable", "embedding": [0.1]},
            {"chunk_id": "ch2", "content_id": "c2", "chunk_index": 0, "chunk_text": "not indexed", "embedding": None},
        ],
        "cb_hubs": [
            {"hub_id": "h1", "title": "Graph Health", "aliases": ["graph hygiene"], "related_terms": ["index health"]}
        ],
        "cb_hub_content": [
            {"hub_id": "h1", "content_id": "c1"},
            {"hub_id": "h1", "content_id": "c2"},
        ],
        "cb_edges": [
            {"from_node": "c1", "relation": "related", "to_node": "h1"},
            {"from_node": "c2", "relation": "related", "to_node": "h1"},
        ],
        "cb_hub_edges": [],
        "cb_aliases": [],
        "cb_alias_candidates": [
            {"term_a": "Graph Health", "term_b": "graph hygiene", "score": 0.9, "status": "pending"}
        ],
        "cb_query_log": [],
    }


def _snapshot(rows=None):
    return RepositoryGraphHealthReader(
        row_sets=rows or _rows(),
        workspace_id="w1",
        now_fn=lambda: NOW,
    ).read_snapshot()


def test_repository_snapshot_feeds_graph_health_service_with_explicit_mode_and_source():
    report = GraphHealthService().evaluate_repository_snapshot(_snapshot(), now=NOW)

    assert report.mode == "repository"
    assert report.data_source == "repository"
    assert report.index_searchability_metrics.total_saved_count == 2
    assert report.index_searchability_metrics.searchable_count == 1
    assert report.hub_recall_metrics.linked_count == 2
    assert report.hub_recall_metrics.retrieval_observed_available is False
    assert "retrieval_observed_unavailable_or_not_provided" in report.limitations
    assert any(value.startswith("unknown_fields:") for value in report.limitations)
    assert "no_full_context_brain_claim" in report.non_claims


def test_missing_chunk_embedding_affects_searchability_and_index_health():
    report = GraphHealthService().evaluate_repository_snapshot(_snapshot(), now=NOW)

    codes = {warning.code for warning in report.warnings}
    assert "MISSING_ITEM_EMBEDDING" in codes
    assert "NULL_EMBEDDING_BACKLOG" in codes
    assert "REPOSITORY_CHUNK_EMBEDDING_MISSING_OR_NULL" in codes
    assert "c2" in report.affected_content_ids
    assert report.index_searchability_metrics.missing_embedding_count == 1
    assert report.index_searchability_metrics.null_embedding_backlog_count == 1


def test_absent_graph_tables_preserve_limitations_and_do_not_crash():
    rows = {
        "content_items": [{"content_id": "c1", "workspace_id": "w1"}],
        "content_chunks": [{"chunk_id": "ch1", "content_id": "c1", "chunk_text": "x", "embedding": [0.1]}],
        "cb_hubs": [],
        "cb_hub_content": [],
    }

    report = GraphHealthService().evaluate_repository_snapshot(_snapshot(rows), now=NOW)

    assert report.mode == "repository"
    assert report.data_source == "repository"
    assert "graph_edges_table_unavailable" in report.limitations
    assert report.status == "limited"
    assert report.topology_metrics.node_count == 0


def test_existing_static_sample_path_defaults_remain_unchanged():
    report = GraphHealthService().evaluate(
        nodes=["a", "b"],
        edges=[("a", "b")],
        content_items=[{"content_id": "a", "searchable": True, "embedding_present": True}],
        now=NOW,
    )

    assert report.mode == "static"
    assert report.data_source == "static"
    assert report.index_searchability_metrics.searchable_count == 1


def test_unavailable_repository_snapshot_is_explicit_and_not_sample_or_live():
    snapshot = RepositoryGraphHealthReader(workspace_id="w1", now_fn=lambda: NOW).unavailable_snapshot(
        "repository connection not configured"
    )

    report = GraphHealthService().evaluate_repository_snapshot(snapshot, now=NOW)

    assert report.mode == "unavailable"
    assert report.data_source == "unavailable"
    assert report.mode != "sample"
    assert "repository connection not configured" in report.limitations
    assert "repository_reader_unavailable" in report.limitations
    assert "empty_graph_or_no_graph_data" in report.limitations


def test_sample_snapshot_refused_to_prevent_sample_as_live_repository_behavior():
    snapshot = replace(_snapshot(), mode="sample", data_source="sample")

    with pytest.raises(ValueError, match="sample"):
        GraphHealthService().evaluate_repository_snapshot(snapshot, now=NOW)


def test_no_api_or_report_generator_imports_required_for_repository_integration():
    import sys

    sys.modules.pop("memory_lab.api.routers.graph_health", None)
    sys.modules.pop("memory_lab.reports.graph_health_report", None)

    report = GraphHealthService().evaluate_repository_snapshot(_snapshot(), now=NOW)

    assert report.mode == "repository"
    assert "memory_lab.api.routers.graph_health" not in sys.modules
    assert "memory_lab.reports.graph_health_report" not in sys.modules
