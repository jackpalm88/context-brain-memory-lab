import ast
import json
from pathlib import Path

import pytest

from memory_lab.ingestion.extraction import (
    NOOP_EXTRACTOR_LIMITATIONS,
    NOOP_EXTRACTOR_MODE,
    NoopContentExtractor,
    make_noop_content_extractor,
)
from memory_lab.ingestion.interfaces import ContentExtractionResult, IngestionTextInput, fixture_to_input

FIXTURE_PATH = Path("tests/fixtures/b17_ingestion/synthetic_ingestion_fixtures.json")
EXTRACTOR_PATH = Path("memory_lab/ingestion/extraction.py")
FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "openai",
    "openrouter",
    "requests",
    "httpx",
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "chromadb",
    "pinecone",
    "qdrant_client",
}
FORBIDDEN_TEXT_PATTERNS = (
    "embed_one",
    "embedding_backfill",
    "backfill",
    "knn",
    "search_v2",
    "search-by-purpose",
    "api_router",
    "APIRouter",
    "private_cb",
    "Context Brain lookup",
    "call_provider",
    "extract_entities",
    "extract_facts",
    "summarize_with_provider",
)


def _sample_input(text="A short caller supplied note.", **kwargs):
    return IngestionTextInput(text=text, item_id="case-001", title="Sample", **kwargs)


def _fixtures():
    return json.loads(FIXTURE_PATH.read_text())["fixtures"]


def _fixture(case):
    matches = [item for item in _fixtures() if item["case"] == case]
    assert matches, f"missing fixture case {case}"
    return matches[0]


def test_factory_returns_focused_noop_content_extractor():
    extractor = make_noop_content_extractor()

    assert isinstance(extractor, NoopContentExtractor)
    assert extractor.mode == NOOP_EXTRACTOR_MODE
    assert extractor.limitations == NOOP_EXTRACTOR_LIMITATIONS


def test_extract_content_returns_existing_contract_result_type():
    result = make_noop_content_extractor().extract_content(_sample_input())

    assert isinstance(result, ContentExtractionResult)
    assert result.mode == NOOP_EXTRACTOR_MODE
    assert result.degraded is True
    assert result.confidence == 0.0


def test_noop_extraction_is_deterministic_for_same_input():
    item = _sample_input(text="Repeated input should not change noop extraction output.")
    extractor = make_noop_content_extractor()

    assert extractor.extract_content(item) == extractor.extract_content(item)


def test_non_whitespace_text_is_preserved_unchanged():
    text = "  Preserve leading and trailing spaces around real supplied text.  \nSecond line."
    result = make_noop_content_extractor().extract_content(_sample_input(text=text))

    assert result.extracted_text == text
    assert result.fields == {}
    assert result.confidence == 0.0
    assert result.degraded is True
    assert result.mode == NOOP_EXTRACTOR_MODE
    assert "noop content extractor only" in result.limitations


@pytest.mark.parametrize("text", ["", "   ", "\n\t  "])
def test_empty_or_whitespace_input_returns_empty_extracted_text(text):
    result = make_noop_content_extractor().extract_content(_sample_input(text=text))

    assert result.extracted_text == ""
    assert result.fields == {}
    assert result.confidence == 0.0
    assert result.degraded is True
    assert result.mode == NOOP_EXTRACTOR_MODE


def test_limitations_are_explicit_on_every_output():
    output = make_noop_content_extractor().extract_content(_sample_input())

    assert output.limitations == NOOP_EXTRACTOR_LIMITATIONS
    assert "noop content extractor only" in output.limitations
    assert "no real content extraction" in output.limitations
    assert "no semantic extraction" in output.limitations
    assert "no entity extraction" in output.limitations
    assert "no fact extraction" in output.limitations
    assert "no summarization" in output.limitations
    assert "no document parsing beyond supplied text" in output.limitations
    assert "no provider calls" in output.limitations
    assert "no stored-record access" in output.limitations
    assert "no vector operation" in output.limitations
    assert "no mutation methods" in output.limitations


def test_fixture_driven_behavior_over_required_b17_cases():
    required_cases = {
        "short note",
        "long document",
        "mixed-language content",
        "empty content",
        "low-quality content",
        "duplicate or near-duplicate content",
        "extraction candidate example",
        "chunking boundary example",
    }
    rows = _fixtures()
    assert required_cases <= {row["case"] for row in rows}
    extractor = make_noop_content_extractor()

    for row in rows:
        result = extractor.extract_content(fixture_to_input(row))
        expected_text = "" if row["text"].strip() == "" else row["text"]
        assert result.extracted_text == expected_text
        assert result.data_source == "synthetic_fixture"
        assert result.fields == {}
        assert result.confidence == 0.0
        assert result.degraded is True
        assert result.mode == NOOP_EXTRACTOR_MODE


def test_mixed_language_input_is_preserved_without_language_understanding_claim():
    row = _fixture("mixed-language content")
    result = make_noop_content_extractor().extract_content(fixture_to_input(row))

    assert result.extracted_text == row["text"]
    assert "Šis" in result.extracted_text
    assert "English" in result.extracted_text
    assert result.confidence == 0.0
    assert "language" not in result.rationale.lower()
    assert "no semantic extraction" in result.limitations


def test_extraction_candidate_fixture_does_not_produce_entities_facts_or_summary():
    row = _fixture("extraction candidate example")
    result = make_noop_content_extractor().extract_content(fixture_to_input(row))

    assert result.extracted_text == row["text"]
    assert result.fields == {}
    assert result.confidence == 0.0
    assert "Mock Event" in result.extracted_text
    assert "Owner:" in result.extracted_text
    assert "Outcome:" in result.extracted_text
    assert "no entity extraction" in result.limitations
    assert "no fact extraction" in result.limitations
    assert "no summarization" in result.limitations


def test_markdown_list_like_text_is_preserved_without_document_parsing():
    text = "# Synthetic Heading\n\n- First public-safe item\n- Second public-safe item\n\nOwner: Fictional Coordinator"
    result = make_noop_content_extractor().extract_content(_sample_input(text=text))

    assert result.extracted_text == text
    assert result.fields == {}
    assert "no document parsing beyond supplied text" in result.limitations


def test_duplicate_or_near_duplicate_content_is_not_deduplicated():
    rows = [row for row in _fixtures() if row["case"] == "duplicate or near-duplicate content"]
    assert len(rows) >= 2
    extractor = make_noop_content_extractor()
    results = [extractor.extract_content(fixture_to_input(row)) for row in rows]

    assert results[0].extracted_text == rows[0]["text"]
    assert results[1].extracted_text == rows[1]["text"]
    assert results[0].extracted_text != results[1].extracted_text
    assert all(result.fields == {} for result in results)


def test_data_source_preserved_without_lookup_or_mutation():
    item = _sample_input(text="source preservation", data_source="caller_supplied_public_test")
    result = make_noop_content_extractor().extract_content(item)

    assert result.data_source == "caller_supplied_public_test"


def test_custom_factory_defaults_remain_deterministic_and_degraded():
    extractor = make_noop_content_extractor(
        mode="noop_extractor_v1_test",
        data_source="synthetic_test_source",
        limitations=("custom noop limitation",),
    )
    item = IngestionTextInput(text="", data_source="")
    result = extractor.extract_content(item)

    assert result.mode == "noop_extractor_v1_test"
    assert result.data_source == "synthetic_test_source"
    assert result.limitations == ("custom noop limitation",)
    assert result.extracted_text == ""
    assert result.degraded is True
    assert result.confidence == 0.0


def test_extractor_module_has_no_provider_db_embedding_or_admin_imports():
    source = EXTRACTOR_PATH.read_text()
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint(FORBIDDEN_IMPORT_ROOTS)
    for pattern in FORBIDDEN_TEXT_PATTERNS:
        assert pattern not in source


def test_noop_extractor_exposes_no_chunker_provider_db_embedding_or_admin_methods():
    extractor = NoopContentExtractor()

    assert callable(extractor.extract_content)
    assert not hasattr(extractor, "chunk_content")
    assert not hasattr(extractor, "embed_one")
    assert not hasattr(extractor, "backfill")
    assert not hasattr(extractor, "knn_search")
    assert not hasattr(extractor, "admin_mutate")
    assert not hasattr(extractor, "search_v2")
