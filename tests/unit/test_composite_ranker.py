from __future__ import annotations

import pytest

from memory_lab.ingestion.chunk_scorer_v2 import compute_chunk_score
from memory_lab.retrieval.composite_ranker import rank_by_composite

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

QUERY = "alpha beta"


def _pgvector(cid, distance, text):
    return {"content_id": cid, "chunk_id": f"chk-{cid}", "text": text,
            "score": 1.0 / (1.0 + distance), "distance": distance, "retrieval_path": "pgvector_knn"}


def _lexical(cid, score, text):
    return {"content_id": cid, "chunk_id": f"chk-{cid}", "text": text,
            "score": score, "retrieval_path": "content_chunk_workspace_scoped"}


def _hub(cid, text, hub_id="hub-1"):
    return {"content_id": cid, "chunk_id": f"chk-{cid}", "text": text,
            "score": 0.95, "hub_match": hub_id, "retrieval_path": "hub_link_workspace_scoped"}


def test_composite_replaces_flat_order_and_hub_no_longer_dominates():
    # Flat scheme would rank the hub row (0.95) first. Composite must not.
    rows = [
        _hub("H", "zeta eta"),                 # flat 0.95 but no semantic/keyword corroboration
        _pgvector("P", 0.2, "alpha beta gamma"),  # strong semantic + keyword
        _lexical("L", 0.7, "alpha only"),         # lexical, weaker
    ]
    ranked = rank_by_composite(rows, QUERY)
    order = [r["content_id"] for r in ranked]

    assert order == ["P", "L", "H"]
    assert order[0] != "H"  # hub flat score no longer dominates


def test_final_score_matches_compute_chunk_score_authority():
    rows = [_pgvector("P", 0.2, "alpha beta gamma")]
    ranked = rank_by_composite(rows, QUERY)

    expected = compute_chunk_score(
        distance=0.2,
        graph_match=[],
        hub_match=[],
        hub_aliases=[],
        hub_related_terms=[],
        query_tokens={"alpha", "beta"},
        chunk_text="alpha beta gamma",
        source_query_count=1,
    )
    assert ranked[0]["final_score"] == pytest.approx(round(expected.final_score, 4))
    assert ranked[0]["score"] == pytest.approx(round(expected.final_score, 4))  # composite surfaced as score


def test_dp1a_lexical_pseudo_distance_gives_vector_like_signal():
    # Lexical score 0.9 -> pseudo distance 0.2 -> vector_score ~0.9 (not zero).
    rows = [_lexical("L", 0.9, "alpha beta")]
    ranked = rank_by_composite(rows, QUERY)
    expected = compute_chunk_score(
        distance=2.0 * (1.0 - 0.9),
        graph_match=[], hub_match=[], hub_aliases=[], hub_related_terms=[],
        query_tokens={"alpha", "beta"}, chunk_text="alpha beta", source_query_count=1,
    )
    assert ranked[0]["final_score"] == pytest.approx(round(expected.final_score, 4))


def test_dp2_hub_without_terms_uses_030_base_not_flat_095():
    rows = [_hub("H", "alpha beta")]  # hub row whose chunk text even matches the query
    ranked = rank_by_composite(rows, QUERY)
    # hub-only -> distance 2.0 -> vector 0; hub_score base 0.30 (no alias/related terms);
    # keyword 2 hits -> 0.4; trust has_hub 0.6.
    expected = compute_chunk_score(
        distance=2.0, graph_match=[], hub_match=["hub-1"], hub_aliases=[], hub_related_terms=[],
        query_tokens={"alpha", "beta"}, chunk_text="alpha beta", source_query_count=1,
    )
    assert ranked[0]["final_score"] == pytest.approx(round(expected.final_score, 4))
    assert ranked[0]["final_score"] < 0.5  # nowhere near the old flat 0.95


def test_sort_tiebreak_prefers_smaller_distance():
    # Two rows with equal final_score should order by smaller distance first.
    rows = [_pgvector("FAR", 0.6, "alpha beta"), _pgvector("NEAR", 0.2, "alpha beta gamma")]
    ranked = rank_by_composite(rows, QUERY)
    # NEAR has higher vector_score, so it should already win on final_score.
    assert ranked[0]["content_id"] == "NEAR"


def test_empty_rows_and_empty_query_are_safe():
    assert rank_by_composite([], QUERY) == []
    assert rank_by_composite([_pgvector("P", 0.2, "alpha")], "") != []
