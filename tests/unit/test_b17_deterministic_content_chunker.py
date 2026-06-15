"""B17 deterministic content chunker tests."""

import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pytest

from memory_lab.ingestion.chunking import (
    DETERMINISTIC_CHUNKER_MODE,
    ChunkerConfig,
    DeterministicContentChunker,
    make_deterministic_content_chunker,
)
from memory_lab.ingestion.interfaces import IngestionTextInput

FIXTURE_PATH = Path("tests/fixtures/b17_ingestion/synthetic_ingestion_fixtures.json")


def _fixtures():
    return json.loads(FIXTURE_PATH.read_text())["fixtures"]


def _fixture(case):
    for item in _fixtures():
        if item["case"] == case:
            return item
    raise AssertionError(f"missing fixture case {case}")


def _chunk_signature(result):
    return [asdict(chunk) if is_dataclass(chunk) else chunk for chunk in result.chunks]


def test_deterministic_output_and_stable_chunk_ids_for_same_input():
    fixture = _fixture("long document")
    chunker = make_deterministic_content_chunker()
    item = IngestionTextInput(
        text=fixture["text"],
        item_id=fixture["id"],
        metadata={"source_case_id": fixture["id"]},
    )

    first = chunker.chunk_content(item)
    second = chunker.chunk_content(item)

    assert _chunk_signature(first) == _chunk_signature(second)
    assert first.mode == DETERMINISTIC_CHUNKER_MODE
    assert all(chunk.chunk_id.startswith(f"{fixture['id']}:det-chunk-v1:") for chunk in first.chunks)
    assert len({chunk.chunk_id for chunk in first.chunks}) == len(first.chunks)


def test_chunk_order_offsets_and_sizes_are_valid_for_long_content():
    fixture = _fixture("long document")
    chunker = DeterministicContentChunker(ChunkerConfig(target_chunk_chars=180, max_chunk_chars=260, min_chunk_chars=60, overlap_chars=40))
    result = chunker.chunk_text(fixture["text"], source_id=fixture["id"], source_case_id=fixture["id"])

    assert len(result.chunks) > 1
    previous = None
    for index, chunk in enumerate(result.chunks):
        assert chunk.index == index
        assert chunk.order == index
        assert chunk.char_start < chunk.char_end
        assert chunk.char_count == len(chunk.text)
        assert fixture["text"][chunk.char_start:chunk.char_end] == chunk.text
        assert chunk.char_count <= 260
        assert chunk.source_id == fixture["id"]
        assert chunk.source_case_id == fixture["id"]
        assert chunk.mode == DETERMINISTIC_CHUNKER_MODE
        if previous is not None:
            assert chunk.char_start >= previous.char_start
            assert previous.char_end - chunk.char_start <= 40
        previous = chunk


def test_empty_content_returns_degraded_limitation_result():
    fixture = _fixture("empty content")
    result = make_deterministic_content_chunker().chunk_text(fixture["text"], source_id=fixture["id"])

    assert result.chunks == ()
    assert result.degraded is True
    assert "empty_content" in result.limitations
    assert result.mode == DETERMINISTIC_CHUNKER_MODE


def test_whitespace_only_content_returns_degraded_limitation_result():
    result = make_deterministic_content_chunker().chunk_text(" \n\t  ", source_id="syn-b17-whitespace-only-001")

    assert result.chunks == ()
    assert result.degraded is True
    assert "whitespace_only_content" in result.limitations


def test_very_short_content_is_single_chunk_with_short_flag():
    fixture = _fixture("short note")
    result = make_deterministic_content_chunker().chunk_text("tiny note", source_id=fixture["id"], source_case_id=fixture["id"])

    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.text == "tiny note"
    assert chunk.boundary_reason == "short_content_single_chunk"
    assert "short_content" in chunk.quality_flags


def test_mixed_language_content_is_preserved_exactly():
    fixture = _fixture("mixed-language content")
    result = make_deterministic_content_chunker().chunk_text(fixture["text"], source_id=fixture["id"])

    assert len(result.chunks) == 1
    assert result.chunks[0].text == fixture["text"]
    assert "Šis" in result.chunks[0].text
    assert "English" in result.chunks[0].text


def test_markdown_list_boundary_preference_is_used_before_hard_split():
    text = "Intro paragraph sets context for a synthetic checklist.\n- First item is intentionally verbose and public safe.\n- Second item continues the invented checklist.\n- Third item closes the sample list."
    chunker = DeterministicContentChunker(ChunkerConfig(target_chunk_chars=75, max_chunk_chars=120, min_chunk_chars=40, overlap_chars=10))
    result = chunker.chunk_text(text, source_id="syn-b17-list-boundary-001")

    assert len(result.chunks) > 1
    assert result.chunks[0].boundary_reason in {"newline_boundary", "list_boundary", "sentence_boundary"}
    assert all(chunk.char_count <= 120 for chunk in result.chunks)


def test_long_paragraph_uses_hard_boundary_fallback_when_no_boundary_exists():
    text = "A" * 240
    chunker = DeterministicContentChunker(ChunkerConfig(target_chunk_chars=70, max_chunk_chars=100, min_chunk_chars=30, overlap_chars=20))
    result = chunker.chunk_text(text, source_id="syn-b17-hard-boundary-001")

    assert len(result.chunks) > 1
    assert result.chunks[0].boundary_reason == "hard_character_boundary"
    assert all(chunk.char_count <= 100 for chunk in result.chunks)


def test_duplicate_near_duplicate_inputs_have_distinct_source_based_ids():
    a = _fixture("duplicate or near-duplicate content")
    b = [item for item in _fixtures() if item["case"] == "duplicate or near-duplicate content" and item["id"] != a["id"]][0]
    chunker = make_deterministic_content_chunker()

    result_a = chunker.chunk_text(a["text"], source_id=a["id"])
    result_b = chunker.chunk_text(b["text"], source_id=b["id"])

    ids_a = {chunk.chunk_id for chunk in result_a.chunks}
    ids_b = {chunk.chunk_id for chunk in result_b.chunks}
    assert ids_a
    assert ids_b
    assert ids_a.isdisjoint(ids_b)
    assert all("duplicate_detection_not_performed" in chunk.quality_flags for chunk in result_a.chunks + result_b.chunks)


def test_fixture_pack_is_chunkable_without_provider_or_store_dependencies():
    chunker = make_deterministic_content_chunker()
    for fixture in _fixtures():
        result = chunker.chunk_text(fixture["text"], source_id=fixture["id"], source_case_id=fixture["id"])
        assert result.mode == DETERMINISTIC_CHUNKER_MODE
        assert "no provider calls" in result.limitations
        assert "no stored-record access" in result.limitations


def test_chunker_source_has_no_forbidden_provider_db_embedding_admin_terms():
    source = Path("memory_lab/ingestion/chunking.py").read_text()
    forbidden_import_patterns = [
        r"import\s+requests\b",
        r"import\s+httpx\b",
        r"from\s+openai\b",
        r"from\s+anthropic\b",
        r"import\s+sqlalchemy\b",
        r"import\s+psycopg",
    ]
    forbidden_terms = [
        "api_key",
        "embedding_backfill",
        "knn",
        "admin_endpoint",
        "search_v2",
        "search-by-purpose",
        "/opt/contentingestor",
        "private_cb",
    ]
    for pattern in forbidden_import_patterns:
        assert not re.search(pattern, source)
    lowered = source.lower()
    for term in forbidden_terms:
        assert term not in lowered
