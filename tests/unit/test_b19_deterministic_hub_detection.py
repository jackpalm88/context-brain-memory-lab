import json
from pathlib import Path

from memory_lab.ingestion.classifiers import (
    DETERMINISTIC_HUB_SIGNAL_MODE,
    DeterministicHubSignalDetector,
    NoopHubDetector,
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


def test_factory_returns_deterministic_hub_detector_not_noop():
    classifiers = make_deterministic_ingestion_signal_classifiers()
    assert isinstance(classifiers.hub_detector, DeterministicHubSignalDetector)
    assert not isinstance(classifiers.hub_detector, NoopHubDetector)
    assert classifiers.hub_detector.mode == DETERMINISTIC_HUB_SIGNAL_MODE


def test_exact_hub_title_match_returns_normalized_candidate():
    row = _fixture("exact hub title match")
    result = DeterministicHubSignalDetector().detect_hubs(_item(row))
    assert tuple(result.hub_candidates) == tuple(row["expected_hubs"])
    assert 0.35 <= result.confidence <= 0.84
    assert result.degraded is False
    assert "deterministic public-safe" in result.rationale


def test_alias_match_returns_candidate():
    row = _fixture("alias hub match")
    result = DeterministicHubSignalDetector().detect_hubs(_item(row))
    assert tuple(result.hub_candidates) == tuple(row["expected_hubs"])
    assert result.confidence >= 0.35


def test_related_term_match_returns_candidate():
    row = _fixture("related term hub match")
    result = DeterministicHubSignalDetector().detect_hubs(_item(row))
    assert tuple(result.hub_candidates) == tuple(row["expected_hubs"])
    assert 0.35 <= result.confidence <= 0.84


def test_no_supplied_candidate_definitions_returns_empty_safely():
    item = IngestionTextInput(text="governance scorecard evidence", title="No candidates", metadata={})
    result = DeterministicHubSignalDetector().detect_hubs(item)
    assert tuple(result.hub_candidates) == ()
    assert result.confidence == 0.0
    assert result.degraded is False


def test_low_signal_returns_empty_safely():
    row = _fixture("low signal")
    result = DeterministicHubSignalDetector().detect_hubs(_item(row))
    assert tuple(result.hub_candidates) == ()
    assert result.confidence == 0.0
    assert result.degraded is False


def test_multiple_candidates_have_deterministic_ordering_and_cap():
    row = _fixture("multiple close candidates")
    detector = DeterministicHubSignalDetector()
    first = detector.detect_hubs(_item(row))
    second = detector.detect_hubs(_item(row))
    assert first == second
    assert 1 < len(tuple(first.hub_candidates)) <= row["expected_max_hubs"]
    assert tuple(first.hub_candidates) == tuple(sorted(first.hub_candidates)) or first.confidence >= 0.35


def test_malformed_candidate_metadata_is_degraded_without_exception():
    item = IngestionTextInput(text="governance evidence", metadata={"hub_candidates": "bad"})
    result = DeterministicHubSignalDetector().detect_hubs(item)
    assert tuple(result.hub_candidates) == ()
    assert result.degraded is True


def test_unusable_input_degraded_without_graph_or_mutation_claims():
    result = DeterministicHubSignalDetector().detect_hubs(IngestionTextInput(text="", title="", metadata={}))
    assert tuple(result.hub_candidates) == ()
    assert result.confidence == 0.0
    assert result.degraded is True
    assert "deterministic public-safe" in result.rationale
    assert "no mutation methods" in result.limitations
    assert "no stored-record access" in result.limitations
