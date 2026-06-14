from datetime import datetime, timezone

from memory_lab.graph.hub_recall_health import HubRecallHealthService

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_hub_linked_retrieval_invisible_content_warns():
    report = HubRecallHealthService().evaluate(
        content_items=[{"content_id": "c1", "searchable": True, "graph_reachable": True}],
        hub_links={"hub1": ["c1"]},
        retrieval_observations={("hub1", "c1"): False},
        now=NOW,
    )
    assert report.metrics.linked_count == 1
    assert report.metrics.searchable_linked_count == 1
    assert report.metrics.hub_linked_not_retrieved_count == 1
    assert "HUB_LINKED_NOT_RETRIEVED" in {w.code for w in report.warnings}


def test_hub_linked_not_searchable_finding():
    report = HubRecallHealthService().evaluate(
        content_items=[{"content_id": "c1", "searchable": False, "indexing_status": "pending"}],
        hub_links={"hub1": ["c1"]},
        retrieval_observations={},
        now=NOW,
    )
    assert report.metrics.linked_count == 1
    assert report.metrics.searchable_linked_count == 0
    assert report.metrics.hub_linked_not_searchable_count == 1
    assert report.findings[0].saved is True
    assert report.findings[0].hub_linked is True
    assert report.findings[0].searchable is False
    assert "HUB_LINKED_NOT_SEARCHABLE" in report.findings[0].warning_codes
    assert "retrieval_observed_not_available" in report.limitations


def test_states_are_distinct_for_saved_searchable_hub_linked_graph_reachable_retrieval_observed():
    report = HubRecallHealthService().evaluate(
        content_items=[{"content_id": "c1", "saved": True, "searchable": False, "graph_reachable": False}],
        hub_links={"hub1": ["c1"]},
        retrieval_observations={("hub1", "c1"): False},
        now=NOW,
    )
    finding = report.findings[0]
    assert finding.saved is True
    assert finding.searchable is False
    assert finding.hub_linked is True
    assert finding.graph_reachable is False
    assert finding.retrieval_observed is False


def test_recall_score_contribution_improves_with_searchable_and_observed():
    weak = HubRecallHealthService().evaluate(
        content_items=[{"content_id": "c1", "searchable": False}],
        hub_links={"hub1": ["c1"]},
        retrieval_observations={("hub1", "c1"): False},
        now=NOW,
    )
    strong = HubRecallHealthService().evaluate(
        content_items=[{"content_id": "c1", "searchable": True}],
        hub_links={"hub1": ["c1"]},
        retrieval_observations={("hub1", "c1"): True},
        now=NOW,
    )
    assert strong.score > weak.score
    assert strong.score == 25
