import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memory_lab.reports.graph_health_report import GraphHealthReportGenerator


@pytest.fixture
def fixed_now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.unit
@pytest.mark.public_safe
def test_generate_all_scenarios_produces_valid_reports(fixed_now):
    scenarios = GraphHealthReportGenerator.generate_all_scenarios(now=fixed_now)

    assert len(scenarios) == 5

    # Verify content of a specific scenario
    healthy_graph = next(s for s in scenarios if s["scenario"] == "healthy_connected_graph")
    assert healthy_graph["status"] == "ok"
    assert healthy_graph["health_score"] >= 90
    assert healthy_graph["component_scores"]["topology_score"] >= 20
    assert healthy_graph["component_scores"]["index_searchability_score"] >= 20
    assert healthy_graph["component_scores"]["hub_recall_score"] >= 20
    assert healthy_graph["component_scores"]["alias_hygiene_score"] >= 5
    assert "no_full_context_brain_claim" in healthy_graph["non_claims"]
    assert not healthy_graph["warnings"]

    missing_embedding = next(s for s in scenarios if s["scenario"] == "missing_embedding_null_searchable")
    assert missing_embedding["status"] == "degraded"
    assert any(w["code"] == "MISSING_ITEM_EMBEDDING" for w in missing_embedding["warnings"])
    assert any(w["code"] == "NULL_EMBEDDING_BACKLOG" for w in missing_embedding["warnings"])

    hub_not_searchable = next(s for s in scenarios if s["scenario"] == "hub_linked_not_searchable_or_retrieved")
    assert hub_not_searchable["status"] == "degraded"
    assert any(w["code"] == "HUB_LINKED_NOT_SEARCHABLE" for w in hub_not_searchable["warnings"])
    assert any(w["code"] == "HUB_LINKED_NOT_RETRIEVED" for w in hub_not_searchable["warnings"])

    alias_candidate = next(s for s in scenarios if s["scenario"] == "alias_candidate_case")
    assert alias_candidate["status"] == "degraded"
    assert len(alias_candidate["alias_candidates"]) >= 2  # D.O.M.A/DOMA, Context Brain/Context_Brain
    assert any(w["code"] == "ALIAS_CANDIDATE_REVIEW_REQUIRED" for w in alias_candidate["warnings"])
    assert "no_alias_candidates_detected_from_provided_labels" not in alias_candidate["limitations"]

    empty_graph = next(s for s in scenarios if s["scenario"] == "empty_graph")
    assert empty_graph["status"] == "limited"
    assert empty_graph["health_score"] >= 0
    assert "empty_graph_or_no_graph_data" in empty_graph["limitations"]
    assert "no_content_index_state_provided" in empty_graph["limitations"]


@pytest.mark.smoke
@pytest.mark.public_safe
def test_script_generates_files(tmp_path, fixed_now, monkeypatch):
    monkeypatch.chdir(tmp_path)  # Run in a temp directory

    from scripts.b15_graph_health_report import main

    main()

    # Verify JSON report
    json_path = tmp_path / "reports" / "b15_graph_health_report_generator_summary.json"
    assert json_path.exists()
    content = json.loads(json_path.read_text(encoding="utf-8"))
    assert content["gate"] == "B15_GRAPH_HEALTH_REPORT_GENERATOR"
    assert content["status"] == "generated"
    assert content["scenario_count"] == 5
    assert content["generated_at"]
    assert len(content["scenarios"]) == 5

    # Verify Markdown report
    md_path = tmp_path / "reports" / "B15_GRAPH_HEALTH_REPORT_GENERATOR.md"
    assert md_path.exists()
    md_content = md_path.read_text(encoding="utf-8")
    assert "# B15 Graph Health Report Generator" in md_content
    assert "## Validation" in md_content
    assert "## Scenarios" in md_content
    assert "### healthy_connected_graph" in md_content
    assert "- **status**: ok" in md_content
    assert "- api_wiring: false" in md_content
