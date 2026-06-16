import json
from pathlib import Path

import pytest

from memory_lab.ingestion.extraction import (
    DETERMINISTIC_EXTRACTOR_MODE,
    DeterministicContentExtractor,
    make_deterministic_content_extractor,
)
from memory_lab.ingestion.interfaces import ContentExtractionResult, IngestionTextInput

FIXTURE_PATH = Path("tests/fixtures/b18_ingestion/synthetic_extraction_domain_fixtures.json")


def _fixtures():
    return json.loads(FIXTURE_PATH.read_text())["fixtures"]


def _fixture(case: str):
    matches = [row for row in _fixtures() if row["case"] == case]
    assert matches, f"missing fixture {case}"
    return matches[0]


def _input(row):
    return IngestionTextInput(
        text=row["text"],
        item_id=row["id"],
        title=row.get("title", ""),
        metadata={"case": row["case"]},
        data_source="synthetic_b18_fixture",
    )


def test_factory_returns_deterministic_extractor():
    extractor = make_deterministic_content_extractor()

    assert isinstance(extractor, DeterministicContentExtractor)
    assert extractor.mode == DETERMINISTIC_EXTRACTOR_MODE


@pytest.mark.parametrize("text", ["", "   ", "\n\t  "])
def test_empty_input_remains_degraded(text):
    result = make_deterministic_content_extractor().extract_content(IngestionTextInput(text=text, title="Blank"))

    assert isinstance(result, ContentExtractionResult)
    assert result.extracted_text == ""
    assert result.degraded is True
    assert result.confidence == 0.0
    assert result.fields["content_kind_hint"] == "empty"
    assert result.fields["length_class"] == "empty"


def test_plain_text_normalizes_line_endings_and_spaces():
    result = make_deterministic_content_extractor().extract_content(
        IngestionTextInput(text="First line\r\nSecond   line", title="Plain")
    )

    assert result.extracted_text == "First line\nSecond line"
    assert result.fields["title_candidate"] == "Plain"
    assert result.fields["length_class"] == "short"
    assert result.degraded is False
    assert 0.0 < result.confidence <= 0.86


def test_markdown_headings_and_bullets_produce_fields():
    text = "# Sample Heading\n\n- First public-safe item\n- Second public-safe item\n\nOwner: Fictional Coordinator"
    result = make_deterministic_content_extractor().extract_content(IngestionTextInput(text=text))

    assert result.fields["headings"] == ("Sample Heading",)
    assert result.fields["bullets"] == ("First public-safe item", "Second public-safe item")
    assert result.fields["key_values"]["owner"] == "Fictional Coordinator"
    assert result.fields["content_kind_hint"] == "key_value_note"
    assert result.degraded is False


def test_htmlish_input_strips_scripts_styles_comments_and_tags():
    row = _fixture("html operations memo")
    result = make_deterministic_content_extractor().extract_content(_input(row))

    assert "secret()" not in result.extracted_text
    assert "display:none" not in result.extracted_text
    assert "hidden" not in result.extracted_text
    assert "<" not in result.extracted_text
    assert "Sample Operations Memo" in result.extracted_text
    assert "First deterministic item" in result.extracted_text
    assert result.fields["bullets"] == ("First deterministic item", "Second local item")
    assert result.degraded is False


def test_key_value_fixture_extracts_deterministic_fields():
    row = _fixture("key value extraction note")
    result = make_deterministic_content_extractor().extract_content(_input(row))

    key_values = result.fields["key_values"]
    assert key_values["mock_event"] == "Sample Review Day"
    assert key_values["owner"] == "Fictional Coordinator"
    assert key_values["outcome"] == "public-safe fixture approved for tests"
    assert key_values["follow-up"] == "verify deterministic parsing only"
    assert result.fields["content_kind_hint"] == row["expected_kind"]


def test_mixed_language_text_preserved_without_language_claim():
    text = "Šis ir izdomāts plānošanas pieraksts. English sample text continues locally."
    result = make_deterministic_content_extractor().extract_content(IngestionTextInput(text=text))

    assert "Šis" in result.extracted_text
    assert "English" in result.extracted_text
    assert "language" not in result.rationale.lower()
    assert "no semantic understanding claim" in result.limitations


def test_same_input_yields_same_output():
    item = _input(_fixture("governance quality evidence"))
    extractor = make_deterministic_content_extractor()

    assert extractor.extract_content(item) == extractor.extract_content(item)


def test_no_dedup_claim_for_near_duplicate_texts():
    extractor = make_deterministic_content_extractor()
    a = extractor.extract_content(IngestionTextInput(text="Project Orchard uses a mock checklist."))
    b = extractor.extract_content(IngestionTextInput(text="Project Orchard uses a sample checklist."))

    assert a.extracted_text != b.extracted_text
    assert "dedup" not in a.rationale.lower()
    assert "dedup" not in b.rationale.lower()
