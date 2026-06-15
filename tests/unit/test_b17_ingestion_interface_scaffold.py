"""B17 provider-neutral ingestion interface scaffold tests."""

import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pytest

from memory_lab.ingestion.interfaces import (
    DEFAULT_LIMITATIONS,
    NOOP_MODE,
    SYNTHETIC_DATA_SOURCE,
    ChunkScoringResult,
    ContentChunkingResult,
    ContentExtractionResult,
    DomainClassificationResult,
    HubDetectionResult,
    IngestionScoringResult,
    IngestionTextInput,
    NoopIngestionInterfaceScaffold,
    TagClassificationResult,
    fixture_to_input,
    make_noop_ingestion_interface,
)

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "b17_ingestion" / "synthetic_ingestion_fixtures.json"
INTERFACE_PATH = Path(__file__).resolve().parents[2] / "memory_lab" / "ingestion" / "interfaces.py"

REQUIRED_CASES = {
    "short note",
    "long document",
    "mixed-language content",
    "empty content",
    "low-quality content",
    "duplicate or near-duplicate content",
    "ambiguous domain",
    "hub candidate text",
    "tag candidate text",
    "chunking boundary example",
    "extraction candidate example",
}


def load_fixtures():
    return json.loads(FIXTURE_PATH.read_text())["fixtures"]


def sample_input():
    fixture = load_fixtures()[0]
    return fixture_to_input(fixture)


def public_fields(result):
    assert is_dataclass(result)
    return asdict(result)


def assert_common_boundary(result):
    data = public_fields(result)
    assert data["mode"] == NOOP_MODE
    assert data["data_source"] in {SYNTHETIC_DATA_SOURCE, "synthetic_fixture"}
    assert data["degraded"] is True
    assert "no mutation methods" in data["limitations"]
    assert any("no real" in item for item in data["limitations"])


def test_all_required_contract_result_types_are_dataclasses():
    for cls in (
        DomainClassificationResult,
        HubDetectionResult,
        TagClassificationResult,
        ContentExtractionResult,
        ContentChunkingResult,
        ChunkScoringResult,
        IngestionScoringResult,
    ):
        instance = cls()
        assert is_dataclass(instance)
        assert_common_boundary(instance)


def test_noop_interface_can_be_instantiated():
    scaffold = make_noop_ingestion_interface()
    assert isinstance(scaffold, NoopIngestionInterfaceScaffold)
    assert scaffold.mode == NOOP_MODE
    assert scaffold.data_source == SYNTHETIC_DATA_SOURCE
    assert scaffold.limitations == DEFAULT_LIMITATIONS


def test_synthetic_fixtures_can_be_used_as_sample_inputs():
    fixtures = load_fixtures()
    cases = {fixture["case"] for fixture in fixtures}
    assert REQUIRED_CASES <= cases
    inputs = [fixture_to_input(fixture) for fixture in fixtures]
    assert all(isinstance(item, IngestionTextInput) for item in inputs)
    assert all(item.item_id.startswith("syn-b17-") for item in inputs)
    assert {item.data_source for item in inputs} == {"synthetic_fixture"}


def test_all_seven_contracts_return_boundary_marked_outputs():
    scaffold = make_noop_ingestion_interface()
    item = sample_input()
    domain = scaffold.classify_domain(item)
    hubs = scaffold.detect_hubs(item)
    tags = scaffold.classify_tags(item)
    extraction = scaffold.extract_content(item)
    chunks = scaffold.chunk_content(item)
    chunk_score = scaffold.score_chunk(chunks.chunks[0])
    ingestion_score = scaffold.score_ingestion(item)

    for result in (domain, hubs, tags, extraction, chunks, chunk_score, ingestion_score):
        assert_common_boundary(result)

    assert domain.domain == "unknown"
    assert domain.confidence == 0.0
    assert hubs.hub_candidates == ()
    assert tags.tags == ()
    assert extraction.extracted_text == item.text
    assert len(chunks.chunks) == 1
    assert chunks.chunks[0].text == item.text
    assert chunk_score.composite == 0.0
    assert ingestion_score.tier_decision == "not_evaluated"


def test_empty_content_produces_no_sample_chunks():
    scaffold = make_noop_ingestion_interface()
    empty_fixture = next(fixture for fixture in load_fixtures() if fixture["case"] == "empty content")
    result = scaffold.chunk_content(fixture_to_input(empty_fixture))
    assert_common_boundary(result)
    assert result.chunks == ()


def test_noop_outputs_are_deterministic_for_same_input():
    scaffold = make_noop_ingestion_interface()
    item = sample_input()
    first = (
        scaffold.classify_domain(item),
        scaffold.detect_hubs(item),
        scaffold.classify_tags(item),
        scaffold.extract_content(item),
        scaffold.chunk_content(item),
        scaffold.score_ingestion(item),
    )
    second = (
        scaffold.classify_domain(item),
        scaffold.detect_hubs(item),
        scaffold.classify_tags(item),
        scaffold.extract_content(item),
        scaffold.chunk_content(item),
        scaffold.score_ingestion(item),
    )
    assert first == second


def test_source_has_no_forbidden_imports_or_runtime_dependencies():
    source = INTERFACE_PATH.read_text()
    forbidden_import_patterns = [
        r"^\s*import\s+(anthropic|openai|openrouter|requests|httpx|psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+(anthropic|openai|openrouter|requests|httpx|psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+memory_lab\.(providers|db|database|api|graph|retrieval)\b",
        r"^\s*import\s+memory_lab\.(providers|db|database|api|graph|retrieval)\b",
    ]
    for pattern in forbidden_import_patterns:
        assert not re.search(pattern, source, re.MULTILINE)


def test_source_has_no_secret_private_path_or_endpoint_literals():
    source = INTERFACE_PATH.read_text().lower()
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
    assert not any(item in source for item in forbidden_literals)


def test_source_exposes_no_backfill_admin_search_or_mutation_methods():
    source = INTERFACE_PATH.read_text().lower()
    forbidden_terms = [
        "def backfill",
        "def mutate",
        "def admin",
        "def search_by_purpose",
        "def search_v2",
        "knn",
        "index mutation",
    ]
    assert not any(term in source for term in forbidden_terms)
