import ast
import json
from pathlib import Path

import pytest

from memory_lab.ingestion.classifiers import (
    NOOP_CLASSIFIER_LIMITATIONS,
    NOOP_CLASSIFIER_MODE,
    NoopDomainClassifier,
    NoopHubDetector,
    NoopTagClassifier,
    make_noop_classifiers,
)
from memory_lab.ingestion.interfaces import IngestionTextInput, fixture_to_input

FIXTURE_PATH = Path("tests/fixtures/b17_ingestion/synthetic_ingestion_fixtures.json")
FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "openai",
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
    "backfill",
    "knn",
    "search_v2",
    "search-by-purpose",
    "api_router",
    "APIRouter",
    "private_cb",
    "Context Brain lookup",
    "provider call",
)


def _sample_input(text="A short caller supplied note.", **kwargs):
    return IngestionTextInput(text=text, item_id="case-001", title="Sample", **kwargs)


def _all_outputs(item=None):
    item = item or _sample_input()
    classifiers = make_noop_classifiers()
    return (
        classifiers.domain_classifier.classify_domain(item),
        classifiers.hub_detector.detect_hubs(item),
        classifiers.tag_classifier.classify_tags(item),
    )


def _fixture_rows():
    payload = json.loads(FIXTURE_PATH.read_text())
    return payload["fixtures"]


def test_factory_returns_focused_noop_classifier_components():
    classifiers = make_noop_classifiers()

    assert isinstance(classifiers.domain_classifier, NoopDomainClassifier)
    assert isinstance(classifiers.hub_detector, NoopHubDetector)
    assert isinstance(classifiers.tag_classifier, NoopTagClassifier)


def test_noop_outputs_are_deterministic_for_same_input():
    item = _sample_input(text="Repeated input should not change noop outputs.")

    first = _all_outputs(item)
    second = _all_outputs(item)

    assert first == second


def test_domain_classifier_returns_unknown_zero_confidence_degraded_result():
    result = NoopDomainClassifier().classify_domain(_sample_input())

    assert result.domain == "unknown"
    assert result.confidence == 0.0
    assert result.degraded is True
    assert result.mode == NOOP_CLASSIFIER_MODE
    assert "no real domain classification" in result.limitations
    assert "domain" in result.rationale


def test_hub_detector_returns_empty_candidates_zero_confidence_degraded_result():
    result = NoopHubDetector().detect_hubs(_sample_input())

    assert tuple(result.hub_candidates) == ()
    assert result.confidence == 0.0
    assert result.degraded is True
    assert result.mode == NOOP_CLASSIFIER_MODE
    assert "no real hub detection" in result.limitations
    assert "hub" in result.rationale


def test_tag_classifier_returns_empty_tags_zero_confidence_degraded_result():
    result = NoopTagClassifier().classify_tags(_sample_input())

    assert tuple(result.tags) == ()
    assert result.confidence == 0.0
    assert result.degraded is True
    assert result.mode == NOOP_CLASSIFIER_MODE
    assert "no real tag classification" in result.limitations
    assert "tag" in result.rationale


def test_limitations_are_explicit_on_every_output():
    for output in _all_outputs():
        assert output.limitations == NOOP_CLASSIFIER_LIMITATIONS
        assert "noop classifier only" in output.limitations
        assert "no semantic understanding" in output.limitations
        assert "no external service calls" in output.limitations
        assert "no stored-record access" in output.limitations
        assert "no vector operation" in output.limitations
        assert "no mutation methods" in output.limitations


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_or_whitespace_input_returns_bounded_noop_outputs(text):
    outputs = _all_outputs(_sample_input(text=text))

    domain, hubs, tags = outputs
    assert domain.domain == "unknown"
    assert tuple(hubs.hub_candidates) == ()
    assert tuple(tags.tags) == ()
    assert all(output.confidence == 0.0 for output in outputs)
    assert all(output.degraded is True for output in outputs)


def test_mixed_language_input_has_no_language_understanding_or_semantic_claim():
    item = _sample_input(text="Latviešu teksts plus English content y español, without inference.")

    for output in _all_outputs(item):
        assert output.mode == NOOP_CLASSIFIER_MODE
        assert output.confidence == 0.0
        assert "no semantic understanding" in output.limitations
        assert "language" not in output.rationale.lower()


def test_fixture_driven_behavior_over_all_b17_synthetic_cases():
    rows = _fixture_rows()
    assert rows
    seen_cases = {row["case"] for row in rows}
    assert "short note" in seen_cases
    assert "long document" in seen_cases
    assert "mixed-language content" in seen_cases
    assert "empty content" in seen_cases
    assert "low-quality content" in seen_cases
    assert "duplicate or near-duplicate content" in seen_cases
    assert "extraction candidate example" in seen_cases
    assert "chunking boundary example" in seen_cases
    assert "ambiguous domain" in seen_cases
    assert "hub candidate text" in seen_cases
    assert "tag candidate text" in seen_cases

    for row in rows:
        item = fixture_to_input(row)
        domain, hubs, tags = _all_outputs(item)
        assert domain.domain == "unknown"
        assert tuple(hubs.hub_candidates) == ()
        assert tuple(tags.tags) == ()
        assert domain.data_source == "synthetic_fixture"
        assert hubs.data_source == "synthetic_fixture"
        assert tags.data_source == "synthetic_fixture"
        assert all(output.confidence == 0.0 for output in (domain, hubs, tags))
        assert all(output.degraded is True for output in (domain, hubs, tags))


def test_candidate_fixtures_do_not_become_real_classifier_claims():
    candidate_cases = {
        "ambiguous domain",
        "hub candidate text",
        "tag candidate text",
        "extraction candidate example",
    }
    rows = [row for row in _fixture_rows() if row["case"] in candidate_cases]
    assert {row["case"] for row in rows} == candidate_cases

    for row in rows:
        domain, hubs, tags = _all_outputs(fixture_to_input(row))
        assert domain.domain == "unknown"
        assert tuple(hubs.hub_candidates) == ()
        assert tuple(tags.tags) == ()
        assert "no real domain classification" in domain.limitations
        assert "no real hub detection" in hubs.limitations
        assert "no real tag classification" in tags.limitations


def test_data_source_preserved_without_lookup_or_mutation():
    item = _sample_input(text="source preservation", data_source="caller_supplied_public_test")

    for output in _all_outputs(item):
        assert output.data_source == "caller_supplied_public_test"


def test_custom_factory_defaults_remain_deterministic_and_degraded():
    classifiers = make_noop_classifiers(
        mode="noop_classifier_v1_test",
        data_source="synthetic_test_source",
        limitations=("custom noop limitation",),
    )
    item = IngestionTextInput(text="", data_source="")

    outputs = (
        classifiers.domain_classifier.classify_domain(item),
        classifiers.hub_detector.detect_hubs(item),
        classifiers.tag_classifier.classify_tags(item),
    )
    assert all(output.mode == "noop_classifier_v1_test" for output in outputs)
    assert all(output.data_source == "synthetic_test_source" for output in outputs)
    assert all(output.limitations == ("custom noop limitation",) for output in outputs)
    assert all(output.degraded is True for output in outputs)


def test_classifier_module_has_no_provider_db_embedding_or_admin_imports():
    source = Path("memory_lab/ingestion/classifiers.py").read_text()
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


def test_noop_classifiers_expose_only_classification_methods():
    assert callable(NoopDomainClassifier().classify_domain)
    assert callable(NoopHubDetector().detect_hubs)
    assert callable(NoopTagClassifier().classify_tags)
    assert not hasattr(NoopDomainClassifier(), "embed_one")
    assert not hasattr(NoopHubDetector(), "backfill")
    assert not hasattr(NoopTagClassifier(), "knn_search")
    assert not hasattr(NoopTagClassifier(), "admin_mutate")
