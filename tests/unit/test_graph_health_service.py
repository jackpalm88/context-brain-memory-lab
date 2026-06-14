from datetime import datetime, timedelta, timezone

from memory_lab.graph.health_models import IndexingStatus
from memory_lab.graph.health_service import GraphHealthService

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_healthy_connected_graph_scores_high():
    report = GraphHealthService().evaluate(
        nodes=["a", "b", "c"],
        edges=[("a", "b"), ("b", "c"), ("a", "c")],
        content_items=[
            {"content_id": "a", "searchable": True, "embedding_present": True, "graph_reachable": True},
            {"content_id": "b", "searchable": True, "embedding_present": True, "graph_reachable": True},
            {"content_id": "c", "searchable": True, "embedding_present": True, "graph_reachable": True},
        ],
        hub_links={"hub1": ["a", "b", "c"]},
        retrieval_observations={("hub1", "a"): True, ("hub1", "b"): True, ("hub1", "c"): True},
        now=NOW,
    )
    assert report.health_score >= 90
    assert report.component_scores.total == report.health_score
    assert report.topology_metrics.largest_component_coverage == 1.0
    assert report.hub_recall_metrics.linked_count == 3
    assert "no_full_context_brain_claim" in report.non_claims


def test_isolated_low_degree_graph_emits_limited_topology_score():
    report = GraphHealthService().evaluate(
        nodes=["a", "b", "c", "isolated"],
        edges=[("a", "b")],
        content_items=[
            {"content_id": "a", "searchable": True, "embedding_present": True},
            {"content_id": "b", "searchable": True, "embedding_present": True},
            {"content_id": "c", "searchable": True, "embedding_present": True},
            {"content_id": "isolated", "searchable": True, "embedding_present": True},
        ],
        now=NOW,
    )
    assert report.topology_metrics.isolated_node_count == 2
    assert report.topology_metrics.low_degree_node_count == 4
    assert report.component_scores.topology_score < 20


def test_missing_embedding_null_searchable_case_warns():
    report = GraphHealthService().evaluate(
        nodes=["missing"],
        content_items=[{"content_id": "missing", "searchable": False, "embedding_present": False}],
        now=NOW,
    )
    codes = {warning.code for warning in report.warnings}
    assert "MISSING_ITEM_EMBEDDING" in codes
    assert "NULL_EMBEDDING_BACKLOG" in codes
    assert "missing" in report.affected_content_ids


def test_stale_index_warning():
    report = GraphHealthService().evaluate(
        content_items=[
            {
                "content_id": "stale",
                "searchable": False,
                "embedding_present": False,
                "searchable_after": NOW - timedelta(hours=1),
            }
        ],
        now=NOW,
    )
    codes = {warning.code for warning in report.warnings}
    assert "STALE_INDEX_NOT_SEARCHABLE" in codes
    assert report.index_searchability_metrics.stale_count == 1


def test_empty_graph_no_graph_data_case():
    report = GraphHealthService().evaluate(now=NOW)
    assert report.status == "limited"
    assert report.health_score <= 20
    assert "empty_graph_or_no_graph_data" in report.limitations
    assert report.topology_metrics.node_count == 0


def test_score_is_clamped_to_0_100():
    report = GraphHealthService().evaluate(
        nodes=["a"],
        content_items=[{"content_id": "a", "indexing_status": IndexingStatus.SEARCHABLE.value, "searchable": True}],
        now=NOW,
    )
    assert 0 <= report.health_score <= 100
