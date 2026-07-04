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
    # M12-4: hub-recall-only rows additionally carry the fixed manual-link boost.
    from memory_lab.retrieval.composite_ranker import MANUAL_LINK_BOOST
    expected = compute_chunk_score(
        distance=2.0, graph_match=[], hub_match=["hub-1"], hub_aliases=[], hub_related_terms=[],
        query_tokens={"alpha", "beta"}, chunk_text="alpha beta", source_query_count=1,
    )
    assert ranked[0]["final_score"] == pytest.approx(round(min(1.0, expected.final_score + MANUAL_LINK_BOOST), 4))
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

def test_p8_hub_term_corroboration_is_acceptance_property_not_new_invariant():
    # P8 validates Doctrine #1 (hub is provenance, not authority) as an Acceptance
    # Suite property: when two hub-linked candidates under the same hub differ only
    # by hub-term textual corroboration, the corroborated candidate must not rank
    # below the non-corroborated candidate.
    rows = [
        {
            "content_id": "HUB_ONLY",
            "chunk_id": "chk-hub-only",
            "text": "ordinary unrelated operational note",
            "score": 0.95,
            "hub_match": "hub-1",
            "hub_aliases": ["durable continuity"],
            "hub_related_terms": ["session recall"],
            "retrieval_path": "hub_link_workspace_scoped",
        },
        {
            "content_id": "HUB_CORROBORATED",
            "chunk_id": "chk-hub-corroborated",
            "text": "ordinary durable continuity operational note",
            "score": 0.95,
            "hub_match": "hub-1",
            "hub_aliases": ["durable continuity"],
            "hub_related_terms": ["session recall"],
            "retrieval_path": "hub_link_workspace_scoped",
        },
    ]

    ranked = rank_by_composite(rows, "neutral query")
    order = [r["content_id"] for r in ranked]

    assert order.index("HUB_CORROBORATED") < order.index("HUB_ONLY")
    assert ranked[0]["final_score"] > ranked[1]["final_score"]

def test_p9_graph_provenance_signal_is_acceptance_property_not_new_invariant():
    # P9 validates that existing graph provenance is fed to the composite scorer.
    # It is an Acceptance Suite property, not Doctrine invariant #6: when otherwise
    # comparable candidates differ only by graph corroboration, the graph-corroborated
    # candidate must not rank below the candidate without graph corroboration.
    rows = [
        {
            "content_id": "NO_GRAPH",
            "chunk_id": "chk-no-graph",
            "text": "alpha beta",
            "score": 0.7,
            "retrieval_path": "content_chunk_workspace_scoped",
        },
        {
            "content_id": "GRAPH_CORROBORATED",
            "chunk_id": "chk-graph-corroborated",
            "text": "alpha beta",
            "score": 0.7,
            "knowledge_path": [
                {"type": "query", "value": "alpha beta"},
                {"type": "graph", "value": "corroborated concept"},
                {"type": "content", "value": "GRAPH_CORROBORATED"},
            ],
            "retrieval_path": "content_chunk_workspace_scoped",
        },
    ]

    ranked = rank_by_composite(rows, QUERY)
    order = [r["content_id"] for r in ranked]

    assert order.index("GRAPH_CORROBORATED") < order.index("NO_GRAPH")
    assert ranked[0]["final_score"] > ranked[1]["final_score"]
