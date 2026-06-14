from dataclasses import replace
from datetime import datetime, timezone

import pytest

from memory_lab.graph.health_service import GraphHealthService
from memory_lab.graph.repository_reader import RepositoryGraphHealthReader
from memory_lab.reports.graph_health_report import GraphHealthReportGenerator

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _repository_rows():
    return {
        "content_items": [
            {"content_id": "c1", "workspace_id": "w1"},
            {"content_id": "c2", "workspace_id": "w1"},
        ],
        "content_chunks": [
            {"chunk_id": "ch1", "content_id": "c1", "chunk_index": 0, "chunk_text": "indexed", "embedding": [0.1]},
            {"chunk_id": "ch2", "content_id": "c2", "chunk_index": 0, "chunk_text": "missing embedding", "embedding": None},
        ],
        "cb_hubs": [{"hub_id": "h1", "title": "Graph Health", "aliases": ["graph hygiene"]}],
        "cb_hub_content": [
            {"hub_id": "h1", "content_id": "c1"},
            {"hub_id": "h1", "content_id": "c2"},
        ],
        "cb_edges": [{"from_node": "c1", "relation": "related", "to_node": "h1"}],
        "cb_hub_edges": [],
        "cb_aliases": [],
        "cb_alias_candidates": [
            {"term_a": "Graph Health", "term_b": "graph hygiene", "score": 0.91, "status": "pending"}
        ],
    }


def _snapshot(rows=None):
    return RepositoryGraphHealthReader(
        row_sets=rows or _repository_rows(),
        workspace_id="w1",
        now_fn=lambda: NOW,
    ).read_snapshot()


@pytest.mark.unit
def test_existing_b15_static_report_behavior_remains_default_static_static():
    report = GraphHealthReportGenerator().generate(
        scenario_name="static_case",
        nodes=["a", "b"],
        edges=[("a", "b")],
        content_items=[{"content_id": "a", "searchable": True, "embedding_present": True}],
        now=NOW,
    )

    assert report["scenario"] == "static_case"
    assert report["mode"] == "static"
    assert report["data_source"] == "static"
    assert report["health_score"] >= 0
    assert "no_full_context_brain_claim" in report["non_claims"]


@pytest.mark.unit
def test_repository_mode_report_includes_explicit_mode_data_source_and_warnings():
    report = GraphHealthReportGenerator().generate_from_repository_snapshot(
        scenario_name="repository_snapshot_case",
        snapshot=_snapshot(),
        now=NOW,
    )

    assert report["scenario"] == "repository_snapshot_case"
    assert report["mode"] == "repository"
    assert report["data_source"] == "repository"
    assert report["index_searchability_metrics"]["total_saved_count"] == 2
    assert report["index_searchability_metrics"]["searchable_count"] == 1
    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert "MISSING_ITEM_EMBEDDING" in warning_codes
    assert "NULL_EMBEDDING_BACKLOG" in warning_codes
    assert "REPOSITORY_CHUNK_EMBEDDING_MISSING_OR_NULL" in warning_codes
    assert any(value.startswith("unknown_fields:") for value in report["limitations"])
    assert "retrieval_observed_unavailable_or_not_provided" in report["limitations"]
    assert report["hub_recall_metrics"]["retrieval_observed_available"] is False


@pytest.mark.unit
def test_repository_mode_report_can_consume_explicit_graph_health_report():
    service_report = GraphHealthService().evaluate_repository_snapshot(_snapshot(), now=NOW)

    report = GraphHealthReportGenerator().generate_from_graph_health_report(
        scenario_name="service_report_case",
        report=service_report,
    )

    assert report["mode"] == "repository"
    assert report["data_source"] == "repository"
    assert report["generated_at"]


@pytest.mark.unit
def test_unavailable_repository_report_is_explicit_and_not_sample_or_live():
    snapshot = RepositoryGraphHealthReader(workspace_id="w1", now_fn=lambda: NOW).unavailable_snapshot(
        "repository unavailable in test"
    )

    report = GraphHealthReportGenerator().generate_from_repository_snapshot(
        scenario_name="repository_unavailable",
        snapshot=snapshot,
        now=NOW,
    )

    assert report["mode"] == "unavailable"
    assert report["data_source"] == "unavailable"
    assert report["mode"] != "sample"
    assert report["data_source"] != "repository"
    assert "repository unavailable in test" in report["limitations"]
    assert "repository_reader_unavailable" in report["limitations"]
    assert "empty_graph_or_no_graph_data" in report["limitations"]


@pytest.mark.unit
def test_sample_snapshot_is_refused_for_repository_report_mode():
    snapshot = replace(_snapshot(), mode="sample", data_source="sample")

    with pytest.raises(ValueError, match="sample"):
        GraphHealthReportGenerator().generate_from_repository_snapshot(
            scenario_name="bad_sample",
            snapshot=snapshot,
            now=NOW,
        )


@pytest.mark.unit
def test_static_report_does_not_masquerade_as_repository_or_live():
    report = GraphHealthReportGenerator().generate(scenario_name="empty_static", now=NOW)

    assert report["mode"] == "static"
    assert report["data_source"] == "static"
    assert report["mode"] != "repository"
    assert report["data_source"] != "repository"


@pytest.mark.unit
def test_repository_report_generation_requires_no_api_import():
    import sys

    sys.modules.pop("memory_lab.api.main", None)
    sys.modules.pop("memory_lab.api.routers.graph_health", None)

    report = GraphHealthReportGenerator().generate_from_repository_snapshot(
        scenario_name="no_api_import",
        snapshot=_snapshot(),
        now=NOW,
    )

    assert report["mode"] == "repository"
    assert "memory_lab.api.main" not in sys.modules
    assert "memory_lab.api.routers.graph_health" not in sys.modules
