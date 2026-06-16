import json
from pathlib import Path

from memory_lab.ingestion.classifiers import (
    DETERMINISTIC_TAG_SIGNAL_MODE,
    DeterministicTagSignalClassifier,
    NoopTagClassifier,
    make_deterministic_ingestion_signal_classifiers,
)
from memory_lab.ingestion.interfaces import IngestionTextInput

FIXTURE_PATH = Path("tests/fixtures/b19_ingestion/synthetic_hub_tag_fixtures.json")


def _fixture(case: str):
    rows = json.loads(FIXTURE_PATH.read_text())["fixtures"]
    matches = [row for row in rows if row["case"] == case]
    assert matches, f"missing fixture {case}"
    return matches[0]


def _item(row):
    return IngestionTextInput(
        text=row["text"],
        item_id=row["id"],
        title=row.get("title", ""),
        metadata=row.get("metadata", {}),
        data_source="synthetic_b19_fixture",
    )


def test_factory_returns_deterministic_tag_classifier_not_noop():
    classifiers = make_deterministic_ingestion_signal_classifiers()
    assert isinstance(classifiers.tag_classifier, DeterministicTagSignalClassifier)
    assert not isinstance(classifiers.tag_classifier, NoopTagClassifier)
    assert classifiers.tag_classifier.mode == DETERMINISTIC_TAG_SIGNAL_MODE


def test_governance_text_returns_expected_tags():
    row = _fixture("exact hub title match")
    result = DeterministicTagSignalClassifier().classify_tags(_item(row))
    tags = set(result.tags)
    for tag in row["expected_tags_any"]:
        assert tag in tags
    assert 0.35 <= result.confidence <= 0.84
    assert result.degraded is False
    assert "deterministic public-safe" in result.rationale


def test_software_testing_text_returns_expected_tags():
    row = _fixture("software testing tags")
    result = DeterministicTagSignalClassifier().classify_tags(_item(row))
    tags = set(result.tags)
    for tag in row["expected_tags_any"]:
        assert tag in tags
    assert 0.35 <= result.confidence <= 0.84


def test_metadata_domain_assisted_case_returns_expected_tags():
    row = _fixture("b18 composability metadata")
    result = DeterministicTagSignalClassifier().classify_tags(_item(row))
    tags = set(result.tags)
    for tag in row["expected_tags_any"]:
        assert tag in tags
    assert result.degraded is False


def test_unsafe_url_ui_terms_rejected():
    row = _fixture("unsafe terms rejected")
    result = DeterministicTagSignalClassifier().classify_tags(_item(row))
    for tag in row["forbidden_tags"]:
        assert tag not in result.tags
    assert all("/" not in tag and "." not in tag for tag in result.tags)


def test_tag_normalization_and_max_cap_enforced():
    text = " ".join([
        "governance public-safe boundary scorecard testing release implementation review validation",
        "documentation operations planning software knowledge base quality evidence tests version repository",
    ])
    result = DeterministicTagSignalClassifier().classify_tags(IngestionTextInput(text=text))
    assert len(tuple(result.tags)) <= 10
    assert all(tag == tag.lower() and " " not in tag and "-" not in tag for tag in result.tags)
    assert "public_safe" in result.tags
    assert "boundary_check" in result.tags


def test_low_signal_returns_empty_tags_safely():
    row = _fixture("low signal")
    result = DeterministicTagSignalClassifier().classify_tags(_item(row))
    assert tuple(result.tags) == ()
    assert result.confidence == 0.0
    assert result.degraded is False


def test_empty_input_degraded():
    result = DeterministicTagSignalClassifier().classify_tags(IngestionTextInput(text="", title="", metadata={}))
    assert tuple(result.tags) == ()
    assert result.confidence == 0.0
    assert result.degraded is True


def test_deterministic_repeatability_and_confidence_bounds():
    row = _fixture("software testing tags")
    classifier = DeterministicTagSignalClassifier()
    first = classifier.classify_tags(_item(row))
    second = classifier.classify_tags(_item(row))
    assert first == second
    assert 0.35 <= first.confidence <= 0.84
    assert "no semantic understanding claim" in first.limitations
