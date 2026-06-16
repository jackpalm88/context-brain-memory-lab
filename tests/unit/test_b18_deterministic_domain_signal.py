import json
from pathlib import Path

from memory_lab.ingestion.classifiers import (
    DETERMINISTIC_DOMAIN_SIGNAL_MODE,
    DOMAIN_TAXONOMY,
    DeterministicDomainSignalClassifier,
    make_deterministic_domain_signal_classifiers,
)
from memory_lab.ingestion.interfaces import IngestionTextInput

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


def test_factory_returns_deterministic_domain_signal_plus_deferred_noops():
    classifiers = make_deterministic_domain_signal_classifiers()

    assert isinstance(classifiers.domain_classifier, DeterministicDomainSignalClassifier)
    assert classifiers.domain_classifier.mode == DETERMINISTIC_DOMAIN_SIGNAL_MODE
    assert tuple(classifiers.hub_detector.detect_hubs(IngestionTextInput(text="hub candidate")).hub_candidates) == ()
    assert tuple(classifiers.tag_classifier.classify_tags(IngestionTextInput(text="tag candidate")).tags) == ()


def test_public_taxonomy_contains_expected_domains():
    for domain in [
        "planning",
        "operations",
        "knowledge_management",
        "software",
        "governance",
        "documentation",
        "quality",
        "ambiguous",
        "unknown",
    ]:
        assert domain in DOMAIN_TAXONOMY


def test_planning_fixture_produces_planning_signal():
    row = _fixture("plain planning note")
    result = DeterministicDomainSignalClassifier().classify_domain(_input(row))

    assert result.domain == row["expected_domain"]
    assert result.confidence > 0.0
    assert result.degraded is False
    assert result.mode == DETERMINISTIC_DOMAIN_SIGNAL_MODE


def test_operations_knowledge_memo_produces_operations_signal():
    row = _fixture("html operations memo")
    result = DeterministicDomainSignalClassifier().classify_domain(_input(row))

    assert result.domain == row["expected_domain"]
    assert result.confidence >= 0.4
    assert result.degraded is False


def test_governance_quality_evidence_produces_governance_signal():
    row = _fixture("governance quality evidence")
    result = DeterministicDomainSignalClassifier().classify_domain(_input(row))

    assert result.domain == row["expected_domain"]
    assert result.confidence >= 0.4
    assert "public-taxonomy" in result.rationale


def test_ambiguous_fixture_returns_ambiguous_low_confidence():
    row = _fixture("ambiguous domain signal")
    result = DeterministicDomainSignalClassifier().classify_domain(_input(row))

    assert result.domain == row["expected_domain"]
    assert 0.0 < result.confidence <= 0.42
    assert result.degraded is False


def test_empty_content_returns_unknown_degraded():
    row = _fixture("empty content")
    result = DeterministicDomainSignalClassifier().classify_domain(_input(row))

    assert result.domain == "unknown"
    assert result.confidence == 0.0
    assert result.degraded is True


def test_hub_tag_fixtures_do_not_produce_hub_or_tag_outputs_in_b18():
    row = _fixture("hub tag deferred note")
    classifiers = make_deterministic_domain_signal_classifiers()
    item = _input(row)

    domain = classifiers.domain_classifier.classify_domain(item)
    hubs = classifiers.hub_detector.detect_hubs(item)
    tags = classifiers.tag_classifier.classify_tags(item)

    assert domain.domain == row["expected_domain"]
    assert tuple(hubs.hub_candidates) == ()
    assert tuple(tags.tags) == ()
    assert hubs.degraded is True
    assert tags.degraded is True


def test_same_input_yields_same_output():
    item = _input(_fixture("plain planning note"))
    classifier = DeterministicDomainSignalClassifier()

    assert classifier.classify_domain(item) == classifier.classify_domain(item)


def test_low_signal_text_returns_unknown_without_semantic_claim():
    result = DeterministicDomainSignalClassifier().classify_domain(
        IngestionTextInput(text="maybe stuff later ???", title="Placeholder")
    )

    assert result.domain == "unknown"
    assert "semantic" not in result.rationale.lower()
    assert "no semantic understanding claim" in result.limitations
