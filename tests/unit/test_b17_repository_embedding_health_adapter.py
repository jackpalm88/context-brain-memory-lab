"""B17 supplied-row repository embedding-health adapter tests."""

import re
from dataclasses import is_dataclass
from pathlib import Path

import pytest

from memory_lab.ingestion.embedding_health_adapter import (
    REPOSITORY_EMBEDDING_HEALTH_ADAPTER_MODE,
    adapt_repository_embedding_health_rows,
    make_repository_embedding_health_adapter,
)
from memory_lab.ingestion.embedding_health import EmbeddingHealthInput

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

SOURCE_PATH = Path("memory_lab/ingestion/embedding_health_adapter.py")


def row(**overrides):
    data = {
        "item_id": "syn-b17-repo-health-item-001",
        "chunk_id": "syn-b17-repo-health-chunk-001",
        "synthetic_id": "syn-b17-repo-health-item-001",
        "source_type": "supplied_repository_rows",
        "embedding_model": "synthetic-model-v1",
        "embedding_dimension": 8,
        "text_length": 120,
    }
    data.update(overrides)
    return data


def assert_adapter_boundary(result):
    assert is_dataclass(result)
    assert result.mode == REPOSITORY_EMBEDDING_HEALTH_ADAPTER_MODE
    assert "supplied in-memory rows only" in result.limitations
    assert "no live repository provider" in result.limitations
    assert "no provider-backed embedding operations" in result.non_claims
    assert "no private Context Brain access" in result.non_claims
    assert all(isinstance(adapted, EmbeddingHealthInput) for adapted in result.rows)
    for record in result.records:
        assert record.mode == "embedding_ops_read_only_health_v1"
        assert "no stored-record access" in record.limitations
        assert "no vector creation implemented" in record.non_claims


def test_all_embeddings_present_maps_to_existing_health_shape():
    result = adapt_repository_embedding_health_rows([
        row(embedding_present=True, embedding_status="present"),
        row(item_id="syn-b17-repo-health-item-002", chunk_id="syn-b17-repo-health-chunk-002", embedding_status="embedded"),
    ])
    assert_adapter_boundary(result)
    assert [record.embedding_state for record in result.records] == ["embedded", "embedded"]
    assert all(record.readiness == "ready_read_only" for record in result.records)


def test_missing_embeddings_map_to_missing_without_backfill_claim():
    result = adapt_repository_embedding_health_rows([
        row(embedding_present=False),
        row(item_id="syn-b17-repo-health-item-002", chunk_id="syn-b17-repo-health-chunk-002", embedding_status="missing"),
    ])
    assert_adapter_boundary(result)
    assert [record.embedding_state for record in result.records] == ["missing_embedding", "missing_embedding"]
    assert all("MISSING_EMBEDDING" in record.warnings for record in result.records)
    assert "no index mutation" in result.non_claims


def test_mixed_present_missing_and_unknown_rows_are_preserved():
    result = adapt_repository_embedding_health_rows([
        row(embedding_present=True),
        row(item_id="syn-b17-repo-health-item-002", chunk_id="syn-b17-repo-health-chunk-002", embedding_present=False),
        row(item_id="syn-b17-repo-health-item-003", chunk_id="syn-b17-repo-health-chunk-003"),
    ])
    assert_adapter_boundary(result)
    assert [record.embedding_state for record in result.records] == ["embedded", "missing_embedding", "unknown"]


def test_unknown_model_or_dimension_degrades_but_does_not_invent_state():
    result = adapt_repository_embedding_health_rows([
        row(embedding_model="", embedding_dimension="unknown"),
    ])
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "unknown"
    assert "UNKNOWN_EMBEDDING_MODEL" in result.records[0].warnings
    assert "UNKNOWN_EMBEDDING_DIMENSION" in result.records[0].warnings


def test_empty_row_set_is_degraded_not_success_claim():
    result = adapt_repository_embedding_health_rows([])
    assert_adapter_boundary(result)
    assert result.rows == ()
    assert result.records == ()
    assert result.degraded is True
    assert "EMPTY_SUPPLIED_ROW_SET" in result.warnings


def test_missing_required_columns_degrades_to_unknown():
    result = adapt_repository_embedding_health_rows([{"source_type": "supplied_repository_rows"}])
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "unknown"
    assert "MISSING_ITEM_ID" in result.records[0].warnings
    assert "MISSING_CHUNK_ID" in result.records[0].warnings


def test_duplicate_row_identifiers_are_warned():
    duplicate = row(embedding_present=True)
    result = make_repository_embedding_health_adapter().adapt_rows([duplicate, duplicate])
    assert_adapter_boundary(result)
    assert result.degraded is True
    assert "DUPLICATE_ROW_IDENTIFIER" in result.warnings
    assert "DUPLICATE_ROW_IDENTIFIER" in result.records[1].warnings


def test_stale_timestamp_only_when_both_timestamps_are_supplied():
    not_stale = adapt_repository_embedding_health_rows([
        row(embedding_present=True, embedding_updated_at="2026-01-01T00:00:00Z"),
    ])
    stale = adapt_repository_embedding_health_rows([
        row(
            embedding_present=True,
            embedding_updated_at="2026-01-01T00:00:00Z",
            source_updated_at="2026-01-02T00:00:00Z",
        ),
    ])
    assert not_stale.records[0].embedding_state == "embedded"
    assert stale.records[0].embedding_state == "stale"
    assert "STALE_EMBEDDING" in stale.records[0].warnings


def test_unavailable_repository_provider_is_supplied_status_only():
    result = adapt_repository_embedding_health_rows([
        row(status="provider_unavailable", embedding_present=True),
    ])
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "unavailable"
    assert result.records[0].data_source == "unavailable"
    assert "REPOSITORY_PROVIDER_UNAVAILABLE_SUPPLIED_STATUS_ONLY" in result.records[0].warnings


def test_partial_or_inconsistent_row_data_degrades_without_mutation_advice():
    result = adapt_repository_embedding_health_rows([
        row(embedding_present=True, embedding_status="failed", error="synthetic_error_code"),
    ])
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "failed"
    assert "INCONSISTENT_EMBEDDING_ROW" in result.records[0].warnings
    assert "EMBEDDING_FAILED" in result.records[0].warnings


def test_zero_text_length_blocks_empty_without_raw_content():
    result = adapt_repository_embedding_health_rows([
        row(text_length=0, embedding_present=False),
    ])
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "blocked_empty"
    assert "BLOCKED_EMPTY_TEXT" in result.records[0].warnings


@pytest.mark.parametrize(
    "unsafe_field, unsafe_value, expected_warning",
    [
        ("api_key", "synthetic redacted marker", "UNSAFE_PRIVATE_VALUE_BLOCKED"),
        ("db_url", "synthetic redacted marker", "UNSAFE_PRIVATE_VALUE_BLOCKED"),
        ("private_path", "synthetic redacted marker", "UNSAFE_PRIVATE_VALUE_BLOCKED"),
        ("sql", "synthetic query payload marker", "UNSAFE_PRIVATE_VALUE_BLOCKED"),
        ("session", object(), "LIVE_REPOSITORY_HANDLE_BLOCKED"),
        ("embedding", [0.1, 0.2, 0.3], "EMBEDDING_VECTOR_VALUE_BLOCKED"),
        ("content_id", "synthetic redacted marker", "PRIVATE_CONTEXT_BRAIN_IDENTIFIER_BLOCKED"),
    ],
)
def test_unsafe_private_looking_input_degrades_or_blocks_safely(unsafe_field, unsafe_value, expected_warning):
    result = adapt_repository_embedding_health_rows([row(**{unsafe_field: unsafe_value})])
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "unavailable"
    assert expected_warning in result.records[0].warnings
    assert "UNSAFE_REPOSITORY_ROW_REDACTED" in result.records[0].warnings
    assert result.rows[0].item_id == "unsafe-redacted"


def test_no_rows_supplied_is_unavailable_without_live_provider():
    result = adapt_repository_embedding_health_rows(None)
    assert_adapter_boundary(result)
    assert result.records[0].embedding_state == "unavailable"
    assert "REPOSITORY_ROWS_UNAVAILABLE" in result.records[0].warnings


def test_source_has_no_db_private_cb_provider_imports_or_operational_methods():
    source = SOURCE_PATH.read_text()
    forbidden_import_patterns = [
        r"^\s*import\s+(anthropic|openai|openrouter|requests|httpx|psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+(anthropic|openai|openrouter|requests|httpx|psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+memory_lab\.(providers|db|database|api|graph|retrieval)\b",
        r"^\s*import\s+memory_lab\.(providers|db|database|api|graph|retrieval)\b",
    ]
    for pattern in forbidden_import_patterns:
        assert not re.search(pattern, source, re.MULTILINE)

    forbidden_snippets = [
        "def generate_embedding",
        "def embed_one",
        "def backfill",
        "def rebuild_index",
        "def mutate_index",
        "CREATE INDEX",
        "search_by_purpose",
        "search_v2",
        "Session(",
        "create_engine",
        "requests.",
        "httpx.",
    ]
    for snippet in forbidden_snippets:
        assert snippet not in source
