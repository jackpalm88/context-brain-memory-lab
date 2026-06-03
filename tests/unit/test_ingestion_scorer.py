"""Unit tests — ingestion scorer (provider-optional). No live API calls."""
import json
import pytest
from unittest.mock import MagicMock, patch

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]


def test_ingestion_scores_to_dict():
    from memory_lab.ingestion.models import IngestionScores
    s = IngestionScores(quality=0.8, relevance=0.7, novelty=0.6, composite=0.72)
    d = s.to_dict()
    assert set(d.keys()) == {"quality", "relevance", "novelty", "composite"}


def test_parse_scores_valid_json():
    from memory_lab.ingestion.scorer import _parse_scores
    raw = json.dumps({"quality": 0.85, "relevance": 0.90, "novelty": 0.70})
    scores = _parse_scores(raw)
    assert abs(scores.quality - 0.85) < 0.001
    expected = 0.85 * 0.35 + 0.90 * 0.35 + 0.70 * 0.30
    assert abs(scores.composite - expected) < 0.001


def test_parse_scores_markdown_fences():
    from memory_lab.ingestion.scorer import _parse_scores
    raw = "```json\n{\"quality\": 0.6, \"relevance\": 0.5, \"novelty\": 0.4}\n```"
    scores = _parse_scores(raw)
    assert scores.quality == 0.6


def test_parse_scores_invalid_returns_fallback():
    from memory_lab.ingestion.scorer import _parse_scores
    scores = _parse_scores("not json at all!!!")
    assert 0.0 <= scores.quality <= 1.0


def test_parse_scores_clamping():
    from memory_lab.ingestion.scorer import _parse_scores
    raw = json.dumps({"quality": 1.5, "relevance": -0.2, "novelty": 0.5})
    scores = _parse_scores(raw)
    assert scores.quality == 1.0
    assert scores.relevance == 0.0
    assert 0.0 <= scores.composite <= 1.0


def test_score_empty_content_fallback():
    from memory_lab.ingestion import scorer
    scores = scorer.score("")
    assert 0.0 <= scores.composite <= 1.0


def test_score_mocked_anthropic():
    from memory_lab.ingestion import scorer
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({"quality": 0.75, "relevance": 0.80, "novelty": 0.65}))]
    mock_client.messages.create.return_value = mock_response
    with patch.object(scorer, "_get_anthropic_client", return_value=mock_client), \
         patch.object(scorer, "_is_circuit_open", return_value=False):
        scores = scorer.score("PostgreSQL indexing strategies for JSONB columns.")
    expected = 0.75 * 0.35 + 0.80 * 0.35 + 0.65 * 0.30
    assert abs(scores.composite - expected) < 0.001


def test_score_circuit_open_fallback():
    from memory_lab.ingestion import scorer
    with patch.object(scorer, "_is_circuit_open", return_value=True), \
         patch.object(scorer, "_get_anthropic_client") as mock_fn:
        scores = scorer.score("content")
    mock_fn.assert_not_called()
    assert 0.0 <= scores.composite <= 1.0


def test_score_api_error_fallback():
    from memory_lab.ingestion import scorer
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("provider overloaded")
    with patch.object(scorer, "_get_anthropic_client", return_value=mock_client), \
         patch.object(scorer, "_is_circuit_open", return_value=False), \
         patch.object(scorer, "_record_failure") as mock_record:
        scores = scorer.score("Test content.")
    mock_record.assert_called_once()
    assert 0.0 <= scores.composite <= 1.0
