"""Unit tests — chunk scorer v2 deterministic formula. Stdlib only."""
import pytest
from memory_lab.ingestion.chunk_scorer_v2 import (
    ScoreComponents, compute_chunk_score, score_to_trust_level, build_ranking_reason,
)

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

QUERY_TOKENS = {"postgresql", "indexing", "strategies", "jsonb"}
GRAPH_MATCH = ["PostgreSQL indexing", "JSONB"]
HUB_MATCH = ["databases"]
HUB_ALIASES = ["db", "database"]
HUB_RELATED = ["sql", "postgres", "index"]


def _sc(**overrides):
    base = dict(
        distance=0.2,
        graph_match=GRAPH_MATCH,
        hub_match=HUB_MATCH,
        hub_aliases=HUB_ALIASES,
        hub_related_terms=HUB_RELATED,
        query_tokens=QUERY_TOKENS,
        chunk_text="PostgreSQL indexing strategies for JSONB columns are important.",
        source_query_count=2,
    )
    base.update(overrides)
    return compute_chunk_score(**base)


def test_import():
    assert callable(compute_chunk_score)
    assert callable(score_to_trust_level)
    assert callable(build_ranking_reason)


def test_full_signals_returns_score_components():
    sc = _sc()
    assert isinstance(sc, ScoreComponents)
    assert 0.0 <= sc.final_score <= 1.0


def test_zero_distance_high_matches():
    sc = _sc(distance=0.0)
    assert sc.final_score >= 0.0


def test_high_distance_no_matches():
    sc = compute_chunk_score(
        distance=2.0,
        graph_match=[],
        hub_match=[],
        hub_aliases=[],
        hub_related_terms=[],
        query_tokens=set(),
        chunk_text="unrelated content",
        source_query_count=0,
    )
    assert 0.0 <= sc.final_score <= 1.0


def test_clamp_upper():
    sc = _sc(distance=0.0, source_query_count=10)
    assert sc.final_score <= 1.0


def test_clamp_lower():
    sc = compute_chunk_score(
        distance=2.0, graph_match=[], hub_match=[], hub_aliases=[],
        hub_related_terms=[], query_tokens=set(), chunk_text="", source_query_count=0,
    )
    assert sc.final_score >= 0.0


def test_ranking_reason_non_empty():
    sc = _sc()
    reason = build_ranking_reason(sc, GRAPH_MATCH, HUB_MATCH, 2)
    assert isinstance(reason, str) and len(reason) > 0


def test_trust_level_high():
    sc_data = ScoreComponents(final_score=0.80)
    assert score_to_trust_level(sc_data) == "high"


def test_trust_level_low():
    sc_data = ScoreComponents(final_score=0.0)
    assert score_to_trust_level(sc_data) == "low"


def test_score_consistency():
    """Same inputs always produce same final_score (deterministic)."""
    sc1 = _sc()
    sc2 = _sc()
    assert sc1.final_score == sc2.final_score
