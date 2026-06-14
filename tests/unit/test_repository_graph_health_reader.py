from datetime import datetime, timezone

import pytest

from memory_lab.graph.repository_reader import (
    ReadOnlySqlViolation,
    RepositoryGraphHealthReader,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _healthy_rows():
    return {
        "content_items": [
            {
                "content_id": "c1",
                "workspace_id": "w1",
                "created_at": NOW,
                "updated_at": NOW,
                "node_type": "fact",
                "quick_summary": "connected searchable item",
                "retrieval_count": 0,
            }
        ],
        "content_chunks": [
            {
                "chunk_id": "ch1",
                "content_id": "c1",
                "workspace_id": "w1",
                "chunk_index": 0,
                "chunk_text": "hello graph",
                "word_count": 2,
                "embedding": [0.1, 0.2],
                "created_at": NOW,
            }
        ],
        "cb_hubs": [
            {
                "hub_id": "h1",
                "workspace_uuid": "w1",
                "title": "Graph Health",
                "type": "topic",
                "aliases": ["graph hygiene"],
                "related_terms": ["index health"],
                "status": "active",
                "owner_defined": True,
            }
        ],
        "cb_hub_content": [
            {"hub_id": "h1", "content_id": "c1", "workspace_id": "w1", "linked_at": NOW}
        ],
        "cb_edges": [
            {
                "from_node": "c1",
                "relation": "related",
                "to_node": "h1",
                "source_id": "s1",
                "confidence": 0.8,
                "workspace_id": "w1",
                "created_at": NOW,
                "updated_at": NOW,
            }
        ],
        "cb_hub_edges": [
            {
                "id": "he1",
                "source_hub_id": "h1",
                "target_hub_id": "h2",
                "type": "related",
                "status": "manual",
                "origin": "manual",
                "confidence": 0.7,
                "workspace_id": "w1",
            }
        ],
        "cb_aliases": [
            {"term": "graph hygiene", "canonical": "Graph Health", "confidence": 0.9, "status": "active"}
        ],
        "cb_alias_candidates": [
            {"term_a": "Graph Health", "term_b": "graph hygiene", "score": 0.92, "source": "repository", "status": "pending"}
        ],
        "cb_query_log": [],
    }


def _reader(row_sets):
    return RepositoryGraphHealthReader(row_sets=row_sets, workspace_id="w1", now_fn=lambda: NOW)


def test_repository_reader_builds_healthy_snapshot_from_fake_rows():
    snapshot = _reader(_healthy_rows()).read_snapshot()

    assert snapshot.data_source == "repository"
    assert snapshot.mode == "repository"
    assert snapshot.workspace_id == "w1"
    assert len(snapshot.content_records) == 1
    assert snapshot.content_records[0].content_id == "c1"
    assert snapshot.content_records[0].item_embedding_state == "unknown"
    assert snapshot.chunk_embedding_states[0].has_embedding is True
    assert snapshot.chunk_embedding_states[0].derived_indexing_status == "searchable"
    assert snapshot.hub_content_links[0].hub_id == "h1"
    assert snapshot.graph_edges[0].from_node == "c1"
    assert snapshot.alias_candidates[0].requires_human_review is True
    assert "content_items.item_embedding_state" in snapshot.unknown_fields
    assert "cb_query_log_has_no_verified_result_content_id_mapping" in snapshot.limitations


def test_graph_health_inputs_preserve_searchability_and_links():
    inputs = _reader(_healthy_rows()).read_graph_health_inputs()

    assert inputs["hub_links"] == {"h1": ["c1"]}
    assert inputs["content_items"] == [
        {
            "content_id": "c1",
            "saved": True,
            "searchable": True,
            "hub_linked": True,
            "graph_reachable": True,
            "retrieval_observed": None,
            "indexing_status": "searchable",
            "embedding_present": True,
            "item_embedding_state": "unknown",
        }
    ]
    assert ("c1", "h1") in inputs["edges"]
    assert ("h1", "h2") in inputs["edges"]


def test_missing_chunk_embedding_becomes_not_searchable_unknown_state():
    rows = _healthy_rows()
    rows["content_chunks"][0]["embedding"] = None

    snapshot = _reader(rows).read_snapshot()
    inputs = _reader(rows).read_graph_health_inputs()

    assert snapshot.chunk_embedding_states[0].has_embedding is False
    assert snapshot.chunk_embedding_states[0].derived_indexing_status == "unknown"
    assert "chunk_embedding_missing_or_null" in snapshot.warnings
    assert inputs["content_items"][0]["searchable"] is False
    assert inputs["content_items"][0]["embedding_present"] is False
    assert inputs["content_items"][0]["indexing_status"] == "unknown"


def test_item_level_embedding_state_remains_unknown_without_item_source():
    rows = _healthy_rows()
    rows["content_items"][0]["embedding"] = [1, 2, 3]

    snapshot = _reader(rows).read_snapshot()

    assert snapshot.content_records[0].item_embedding_state == "unknown"
    assert "content_items.item_embedding_state" in snapshot.unknown_fields


def test_hub_recall_inputs_include_hub_content_links_and_unknown_retrieval_observed():
    inputs = _reader(_healthy_rows()).read_hub_recall_inputs("h1")

    assert inputs["hub_id"] == "h1"
    assert inputs["hub_links"] == {"h1": ["c1"]}
    assert inputs["retrieval_observations"] == {}
    assert "hub_recall.retrieval_observed_without_explicit_result_content_ids" in inputs["unknown_fields"]


def test_weak_content_retrieval_counter_does_not_claim_hub_specific_observation():
    rows = _healthy_rows()
    rows["content_items"][0]["retrieval_count"] = 3
    rows["content_items"][0]["last_retrieved_at"] = NOW

    snapshot = _reader(rows).read_snapshot()
    inputs = _reader(rows).read_hub_recall_inputs("h1")

    assert snapshot.retrieval_observations[0].strength == "weak_content_counter"
    assert snapshot.retrieval_observations[0].hub_id is None
    assert inputs["retrieval_observations"] == {}


def test_graph_tables_absent_or_empty_are_handled_without_crash():
    rows = {
        "content_items": [{"content_id": "c1", "workspace_id": "w1"}],
        "content_chunks": [],
        "cb_hubs": [],
        "cb_hub_content": [],
    }

    snapshot = _reader(rows).read_snapshot()
    inputs = _reader(rows).read_graph_health_inputs()

    assert snapshot.graph_edges == ()
    assert "graph_edges_table_unavailable" in snapshot.limitations
    assert inputs["nodes"] == []
    assert inputs["content_items"][0]["searchable"] is False
    assert inputs["content_items"][0]["embedding_present"] is None


def test_alias_candidate_rows_normalize_deterministically():
    rows = _healthy_rows()
    rows["cb_alias_candidates"] = [
        {"term_a": "zeta", "term_b": "alpha", "score": 0.1, "status": "pending"},
        {"term_a": "alpha", "term_b": "beta", "score": 0.9, "status": "pending"},
        {"term_a": "ignored", "term_b": "archived", "score": 1.0, "status": "archived"},
    ]

    result = _reader(rows).read_alias_candidate_inputs()

    assert [candidate.term_a for candidate in result["alias_candidates"]] == ["alpha", "zeta"]
    assert all(candidate.requires_human_review for candidate in result["alias_candidates"])
    assert "alpha" in result["alias_labels"]
    assert "Graph Health" in result["alias_labels"]


def test_unavailable_snapshot_is_explicit_and_not_sample():
    snapshot = RepositoryGraphHealthReader(workspace_id="w1", now_fn=lambda: NOW).unavailable_snapshot(
        "connection not configured"
    )

    assert snapshot.mode == "unavailable"
    assert snapshot.data_source == "unavailable"
    assert snapshot.mode != "sample"
    assert "connection not configured" in snapshot.limitations
    assert "repository_reader_unavailable" in snapshot.limitations


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO content_items VALUES (1)",
        "UPDATE content_items SET tier = 'x'",
        "DELETE FROM content_items",
        "DROP TABLE content_items",
        "ALTER TABLE content_items ADD COLUMN x int",
        "CREATE TABLE x(id int)",
        "TRUNCATE content_items",
        "REINDEX TABLE content_items",
        "VACUUM content_items",
        "WITH x AS (SELECT 1) DELETE FROM content_items",
    ],
)
def test_sql_guard_rejects_mutation_statements(sql):
    reader = RepositoryGraphHealthReader()

    with pytest.raises(ReadOnlySqlViolation):
        reader._ensure_read_only_sql(sql)


@pytest.mark.parametrize("sql", ["SELECT * FROM content_items", "WITH x AS (SELECT 1) SELECT * FROM x"])
def test_sql_guard_allows_select_and_with(sql):
    RepositoryGraphHealthReader()._ensure_read_only_sql(sql)


def test_no_api_router_or_report_generator_imports_required():
    import sys

    sys.modules.pop("memory_lab.api.routers.graph_health", None)
    sys.modules.pop("memory_lab.reports.graph_health_report", None)

    reader = _reader(_healthy_rows())
    snapshot = reader.read_snapshot()

    assert snapshot.mode == "repository"
    assert "memory_lab.api.routers.graph_health" not in sys.modules
    assert "memory_lab.reports.graph_health_report" not in sys.modules
