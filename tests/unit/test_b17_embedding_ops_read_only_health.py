"""B17 deterministic read-only embedding health evaluator tests."""

import re
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pytest

from memory_lab.ingestion.chunk_scoring import make_deterministic_chunk_scorer
from memory_lab.ingestion.embedding_health import (
    EMBEDDING_HEALTH_MODE,
    HEALTH_STATES,
    EmbeddingHealthEvaluator,
    EmbeddingHealthInput,
    evaluate_embedding_health,
    evaluate_embedding_health_rows,
    make_embedding_health_evaluator,
)
from memory_lab.ingestion.interfaces import ContentChunk

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

SOURCE_PATH = Path("memory_lab/ingestion/embedding_health.py")


def chunk(text="Synthetic public-safe chunk with enough context for local checks.", chunk_id="syn-b17-emb-health-chunk-001"):
    return ContentChunk(
        chunk_id=chunk_id,
        text=text,
        order=0,
        index=0,
        char_start=0,
        char_end=len(text),
        char_count=len(text),
        source_id="syn-b17-emb-health-item-001",
        source_case_id="syn-b17-emb-health-case-001",
        boundary_reason="sentence_boundary",
        mode="deterministic_chunker_v1",
        data_source="synthetic_fixture",
        degraded=False,
        limitations=("deterministic character chunk",),
    )


def base_row(**overrides):
    c = overrides.pop("chunk", chunk())
    row = {
        "item_id": "syn-b17-emb-health-item-001",
        "synthetic_id": "syn-b17-emb-health-item-001",
        "chunk_id": c.chunk_id,
        "chunk": c,
        "chunk_score": make_deterministic_chunk_scorer().score_chunk(c),
        "data_source": "synthetic_fixture",
        "source_available": True,
    }
    row.update(overrides)
    return row


def assert_record_boundary(record, expected_state):
    assert is_dataclass(record)
    data = asdict(record)
    assert data["mode"] == EMBEDDING_HEALTH_MODE
    assert data["embedding_state"] == expected_state
    assert data["embedding_state"] in HEALTH_STATES
    assert data["data_source"] in {"synthetic_fixture", "public_safe_export", "unavailable"}
    assert "no semantic readiness claim" in data["non_claims"]
    assert "no provider-backed embedding operations" in data["non_claims"]
    assert "no stored-record access" in data["limitations"]
    assert isinstance(data["warnings"], tuple)
    assert isinstance(data["limitations"], tuple)


def test_all_health_states_are_declared_in_design_order():
    assert HEALTH_STATES == (
        "embedded",
        "missing_embedding",
        "pending",
        "blocked_empty",
        "blocked_low_quality",
        "blocked_reextract",
        "stale",
        "failed",
        "unknown",
        "unavailable",
    )


def test_embedded_when_present_and_not_stale_or_failed():
    record = evaluate_embedding_health(
        base_row(
            embedding_present=True,
            embedding_updated_at="2026-01-02T00:00:00Z",
            source_updated_at="2026-01-01T00:00:00Z",
        )
    )
    assert_record_boundary(record, "embedded")
    assert record.readiness == "ready_read_only"
    assert record.reason == "embedding_present_flag_true"
    assert "SEMANTIC_READINESS_NOT_CLAIMED" in record.warnings


def test_missing_embedding_when_false_and_otherwise_eligible():
    record = evaluate_embedding_health(base_row(embedding_present=False))
    assert_record_boundary(record, "missing_embedding")
    assert record.readiness == "not_ready_missing_embedding"
    assert "MISSING_EMBEDDING" in record.warnings


def test_pending_when_status_indicates_queued_or_pending():
    record = evaluate_embedding_health(base_row(embedding_status="queued"))
    assert_record_boundary(record, "pending")
    assert record.readiness == "not_ready_pending"
    assert "EMBEDDING_PENDING" in record.warnings


def test_blocked_empty_for_empty_or_whitespace_chunk():
    empty_chunk = chunk("   \n\t", "syn-b17-emb-health-empty-001")
    score = make_deterministic_chunk_scorer().score_chunk(empty_chunk)
    record = evaluate_embedding_health(base_row(chunk=empty_chunk, chunk_score=score, embedding_present=False))
    assert_record_boundary(record, "blocked_empty")
    assert record.readiness == "blocked"
    assert "BLOCKED_EMPTY_TEXT" in record.warnings


def test_blocked_low_quality_for_low_deterministic_mechanical_score():
    low_chunk = ContentChunk(
        chunk_id="syn-b17-emb-health-low-quality-001",
        text="tiny",
        order=0,
        index=0,
        char_start=0,
        char_end=4,
        char_count=4,
        source_id="syn-b17-emb-health-item-001",
        source_case_id="syn-b17-emb-health-case-001",
        boundary_reason="hard_boundary_guard",
        data_source="synthetic_fixture",
        degraded=True,
        limitations=("synthetic low quality",),
    )
    score = make_deterministic_chunk_scorer().score_chunk(low_chunk)
    assert score.recommendation == "block"
    record = evaluate_embedding_health(base_row(chunk=low_chunk, chunk_score=score, embedding_present=False))
    assert_record_boundary(record, "blocked_low_quality")
    assert record.reason == "mechanical_chunk_score_blocked"
    assert "BLOCKED_LOW_MECHANICAL_QUALITY" in record.warnings


def test_blocked_reextract_when_explicitly_required():
    record = evaluate_embedding_health(base_row(requires_reextract=True, embedding_present=True))
    assert_record_boundary(record, "blocked_reextract")
    assert record.readiness == "blocked_reextract_required"
    assert "BLOCKED_REEXTRACT_REQUIRED" in record.warnings


def test_stale_when_source_timestamp_is_newer_than_embedding_timestamp():
    record = evaluate_embedding_health(
        base_row(
            embedding_present=True,
            embedding_updated_at="2026-01-01T00:00:00Z",
            source_updated_at="2026-01-02T00:00:00Z",
        )
    )
    assert_record_boundary(record, "stale")
    assert record.reason == "source_newer_than_embedding"
    assert "STALE_EMBEDDING" in record.warnings


def test_failed_when_failure_status_or_reason_exists():
    record = evaluate_embedding_health(base_row(embedding_status="failed", failure_reason="synthetic_error_code"))
    assert_record_boundary(record, "failed")
    assert record.readiness == "not_ready_failed"
    assert "EMBEDDING_FAILED" in record.warnings


def test_unknown_when_input_cannot_prove_embedding_state():
    record = evaluate_embedding_health(base_row())
    assert_record_boundary(record, "unknown")
    assert record.readiness == "unknown"
    assert "EMBEDDING_STATE_UNKNOWN" in record.warnings


def test_unavailable_when_source_rows_or_dependency_are_unavailable():
    record = evaluate_embedding_health(None)
    assert_record_boundary(record, "unavailable")
    assert record.readiness == "unavailable"
    assert "EMBEDDING_HEALTH_SOURCE_UNAVAILABLE" in record.warnings

    unavailable = evaluate_embedding_health(base_row(source_available=False, embedding_present=True))
    assert_record_boundary(unavailable, "unavailable")


def test_missing_embedding_vs_unknown_distinction():
    missing = evaluate_embedding_health(base_row(embedding_present=False))
    unknown = evaluate_embedding_health(base_row())
    assert missing.embedding_state == "missing_embedding"
    assert missing.reason == "embedding_flag_false"
    assert unknown.embedding_state == "unknown"
    assert unknown.reason == "embedding_state_not_proven_by_supplied_row"


def test_evaluator_is_deterministic_for_same_rows():
    rows = [
        base_row(embedding_present=True),
        base_row(embedding_present=False),
        base_row(embedding_status="pending"),
    ]
    evaluator = make_embedding_health_evaluator()
    assert evaluator.evaluate_embedding_health_rows(rows) == evaluator.evaluate_embedding_health_rows(rows)
    assert evaluate_embedding_health_rows(rows) == evaluator.evaluate_embedding_health_rows(rows)


def test_batch_summary_counts_states_and_warnings():
    evaluator = EmbeddingHealthEvaluator()
    summary = evaluator.summarize(
        [
            base_row(embedding_present=True),
            base_row(embedding_present=False),
            base_row(embedding_status="pending"),
            None,
        ]
    )
    assert summary.mode == EMBEDDING_HEALTH_MODE
    assert summary.total_chunks == 4
    assert summary.state_counts["embedded"] == 1
    assert summary.state_counts["missing_embedding"] == 1
    assert summary.state_counts["pending"] == 1
    assert summary.state_counts["unavailable"] == 1
    assert summary.degraded_count == 3


def test_dataclass_input_is_supported():
    record = evaluate_embedding_health(
        EmbeddingHealthInput(
            item_id="syn-b17-emb-health-dataclass-001",
            synthetic_id="syn-b17-emb-health-dataclass-001",
            chunk_id="syn-b17-emb-health-dataclass-chunk-001",
            chunk_text="Synthetic public-safe dataclass input row.",
            embedding_status="present",
        )
    )
    assert_record_boundary(record, "embedded")


def test_source_has_no_provider_db_private_cb_imports_or_operational_methods():
    source = SOURCE_PATH.read_text()
    forbidden_import_patterns = [
        r"^\s*import\s+(anthropic|openai|openrouter|requests|httpx|psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+(anthropic|openai|openrouter|requests|httpx|psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+memory_lab\.(providers|db|database|api|graph|retrieval)\b",
        r"^\s*import\s+memory_lab\.(providers|db|database|api|graph|retrieval)\b",
    ]
    for pattern in forbidden_import_patterns:
        assert not re.search(pattern, source, re.MULTILINE)

    forbidden_defs = [
        "def generate_embedding",
        "def embed_one",
        "def rebuild_index",
        "def mutate",
        "def admin",
        "def search_v2",
        "def search_by_purpose",
    ]
    lowered = source.lower()
    assert not any(term in lowered for term in forbidden_defs)


def test_source_has_no_private_ids_paths_secrets_or_provider_endpoints():
    lowered = SOURCE_PATH.read_text().lower()
    forbidden_literals = [
        "/opt/",
        "conting.superagents.solutions",
        "api.openai.com",
        "api.anthropic.com",
        "openrouter.ai",
        "sk-",
        "postgres://",
        "postgresql://",
        "database_url",
        "c:\\users\\",
    ]
    assert not any(item in lowered for item in forbidden_literals)
